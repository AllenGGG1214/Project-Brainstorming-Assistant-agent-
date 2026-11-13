"""Turn uploaded files into text chunks for retrieval.

Accepts plain text, Markdown, source/config files, PDF, and ZIP archives of a
repository. Everything is treated as untrusted data: archive paths are
sanitised, sizes are capped, and binary content is skipped.
"""
import io
import posixpath
import zipfile

MAX_UPLOAD_BYTES = 10 * 1024 * 1024        # raw upload size
MAX_FILE_TEXT_BYTES = 1024 * 1024          # per extracted file
MAX_ARCHIVE_TOTAL_BYTES = 20 * 1024 * 1024 # uncompressed total for a ZIP
MAX_ARCHIVE_FILES = 400
CHUNK_CHARS = 3200                         # roughly 800 tokens
CHUNK_OVERLAP_LINES = 6

TEXT_EXTENSIONS = {
    '.md', '.markdown', '.txt', '.rst', '.adoc', '.csv', '.tsv',
    '.json', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.env.example', '.xml', '.sql', '.graphql', '.proto',
    '.py', '.ipynb', '.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs', '.vue', '.svelte', '.html', '.css', '.scss',
    '.java', '.kt', '.kts', '.scala', '.go', '.rs', '.c', '.h', '.cpp', '.hpp', '.cc', '.cs', '.swift', '.m',
    '.rb', '.php', '.pl', '.lua', '.r', '.jl', '.dart', '.ex', '.exs', '.erl', '.hs', '.clj', '.sh', '.ps1', '.bat',
    '.gradle', '.tf', '.dockerfile',
}
TEXT_FILENAMES = {'dockerfile', 'makefile', 'readme', 'license', 'procfile', 'gemfile', 'requirements.txt'}
SKIP_DIRS = {'.git', 'node_modules', '.venv', 'venv', '__pycache__', 'dist', 'build', '.next', 'target', '.idea', '.vscode'}


class IngestError(ValueError):
    pass


def _extension(name):
    lower = name.lower()
    if lower.endswith('.env.example'):
        return '.env.example'
    return posixpath.splitext(lower)[1]


def is_text_name(name):
    base = posixpath.basename(name).lower()
    return _extension(name) in TEXT_EXTENSIONS or base in TEXT_FILENAMES


def _decode(data):
    if b'\x00' in data[:4096]:
        return None
    for encoding in ('utf-8', 'utf-16'):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode('latin-1')


def _safe_member(name):
    """Return a normalised relative path, or None if the entry must be skipped."""
    name = name.replace('\\', '/')
    if name.startswith('/') or (len(name) > 1 and name[1] == ':'):
        return None
    normalised = posixpath.normpath(name)
    parts = normalised.split('/')
    if normalised.startswith('..') or '..' in parts:
        return None
    if any(part in SKIP_DIRS for part in parts[:-1]):
        return None
    return normalised


def _pdf_text(data):
    from pypdf import PdfReader
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [(page.extract_text() or '') for page in reader.pages[:300]]
    except Exception as exc:
        raise IngestError('The PDF could not be read. Upload a text-based PDF or export it as Markdown.') from exc
    return '\n'.join(f'[page {i + 1}]\n{text}' for i, text in enumerate(pages) if text.strip())


def extract(filename, data):
    """Return (kind, [(path, text), ...]) for an uploaded file."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise IngestError('The file is larger than 10 MB.')
    lower = filename.lower()
    if lower.endswith('.zip'):
        return 'archive', _extract_zip(data)
    if lower.endswith('.pdf'):
        text = _pdf_text(data)
        if not text.strip():
            raise IngestError('No text was found in the PDF.')
        return 'pdf', [(filename, text)]
    if not is_text_name(filename):
        raise IngestError('Unsupported file type. Upload text, Markdown, code, PDF, or a ZIP of a repository.')
    if len(data) > MAX_FILE_TEXT_BYTES:
        raise IngestError('Text files must be smaller than 1 MB.')
    text = _decode(data)
    if text is None or not text.strip():
        raise IngestError('The file is empty or not a text file.')
    return 'text', [(filename, text)]


def _extract_zip(data):
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise IngestError('The ZIP file is invalid.') from exc
    files, total = [], 0
    with archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            path = _safe_member(info.filename)
            if not path or not is_text_name(path) or info.file_size > MAX_FILE_TEXT_BYTES:
                continue
            total += info.file_size
            if total > MAX_ARCHIVE_TOTAL_BYTES or len(files) >= MAX_ARCHIVE_FILES:
                raise IngestError('The archive contains too much text. Remove generated or vendored files and try again.')
            with archive.open(info) as handle:
                raw = handle.read(MAX_FILE_TEXT_BYTES + 1)
            if len(raw) > MAX_FILE_TEXT_BYTES:
                continue
            text = _decode(raw)
            if text and text.strip():
                files.append((path, text))
    if not files:
        raise IngestError('No readable text or code files were found in the archive.')
    return files


def chunk(path, text, limit=CHUNK_CHARS, overlap=CHUNK_OVERLAP_LINES):
    """Split text into line-aligned chunks with a small overlap, keeping line ranges."""
    lines = text.replace('\r\n', '\n').split('\n')
    pieces, start = [], 0
    while start < len(lines):
        size, end = 0, start
        while end < len(lines) and (size + len(lines[end]) + 1 <= limit or end == start):
            size += len(lines[end]) + 1
            end += 1
        body = '\n'.join(lines[start:end]).strip()
        if body:
            pieces.append({'location': f'{path}:{start + 1}-{end}', 'text': body[:limit * 2]})
        if end >= len(lines):
            break
        start = max(end - overlap, start + 1)
    return pieces


def ingest(filename, data):
    kind, files = extract(filename, data)
    pieces = [piece for path, text in files for piece in chunk(path, text)]
    return kind, pieces
