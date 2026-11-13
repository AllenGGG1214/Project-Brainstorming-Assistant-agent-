from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

STAGES = ['organize', 'research', 'functions', 'prototype', 'architecture']
Stage = Literal['organize', 'research', 'functions', 'prototype', 'architecture']


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class RegisterRequest(StrictModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=12, max_length=128)
    invite_code: str = Field(min_length=1, max_length=256)


class LoginRequest(StrictModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)


class ProjectCreate(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    idea: str = Field(min_length=10, max_length=12000)
    constraints: str = Field(default='', max_length=4000)
    mode: Literal['demo', 'live'] = 'demo'

    @model_validator(mode='after')
    def trim(self):
        self.title = self.title.strip()
        self.idea = self.idea.strip()
        if not self.title or len(self.idea) < 10:
            raise ValueError('Enter a title and a project idea of at least 10 characters.')
        return self


class GenerateRequest(StrictModel):
    feedback: str = Field(default='', max_length=4000)


class AcceptRequest(StrictModel):
    artifact_id: str
    decision: Literal['GO', 'PIVOT', 'STOP'] | None = None
    revised_idea: str = Field(default='', max_length=12000)


class Brief(StrictModel):
    markdown: str
    assumptions: list[str]
    search_terms: list[str]


class Comparison(StrictModel):
    name: str
    overlap: str
    difference: str
    evidence: Literal['Verified', 'Inferred', 'Assumption', 'Unknown']
    source_urls: list[str]


class Research(StrictModel):
    markdown: str
    recommendation: Literal['GO', 'PIVOT', 'STOP']
    rationale: str
    comparisons: list[Comparison]
    uncertainty: list[str]


class Function(StrictModel):
    id: str = Field(pattern=r'^FL-\d{3}$')
    name: str
    value: str
    requirement: str
    tier: Literal['MVP', 'Standard', 'Stretch']
    dependencies: list[str]
    low_days: float = Field(ge=0)
    likely_days: float = Field(ge=0)
    high_days: float = Field(ge=0)
    risk: str

    @model_validator(mode='after')
    def ordered(self):
        if not self.low_days <= self.likely_days <= self.high_days:
            raise ValueError('Effort estimates must satisfy low ≤ likely ≤ high.')
        return self


class Functions(StrictModel):
    markdown: str
    functions: list[Function] = Field(min_length=1)
    daily_rate: float = Field(ge=0)
    currency: str
    assumptions: list[str]

    @model_validator(mode='after')
    def validate_dependencies(self):
        seen = set()
        for f in self.functions:
            if f.id in seen or not set(f.dependencies) <= seen:
                raise ValueError('Function IDs must be unique, and dependencies must reference earlier functions.')
            seen.add(f.id)
        if not any(f.tier == 'MVP' for f in self.functions):
            raise ValueError('At least one MVP function is required.')
        return self


class Mapping(StrictModel):
    function_id: str
    implementation: str
    behavior: Literal['interactive', 'mocked', 'deferred']


class Prototype(StrictModel):
    markdown: str
    html: str = Field(min_length=50, max_length=150000)
    mappings: list[Mapping]


class Component(StrictModel):
    name: str
    function_ids: list[str]
    responsibility: str


class Architecture(StrictModel):
    markdown: str
    mermaid: str
    components: list[Component]
    tradeoffs: list[str]


OUTPUTS = dict(zip(STAGES, [Brief, Research, Functions, Prototype, Architecture]))


def validate_traceability(stage, result, context):
    if stage not in ('prototype', 'architecture'):
        return
    functions = context['functions']['functions']
    expected = {f['id'] for f in functions}
    if stage == 'prototype':
        ids = [m.function_id for m in result.mappings]
        if len(ids) != len(set(ids)) or set(ids) != expected:
            raise ValueError('Prototype mappings must cover every function ID exactly once, without additions.')
        mvp = {f['id'] for f in functions if f['tier'] == 'MVP'}
        if any(m.function_id in mvp and m.behavior == 'deferred' for m in result.mappings):
            raise ValueError('MVP functions cannot be deferred.')
        if '<html' not in result.html.lower():
            raise ValueError('The prototype must be a complete HTML document.')
    else:
        ids = {i for c in result.components for i in c.function_ids}
        if ids != expected or any(not c.function_ids for c in result.components):
            raise ValueError('Architecture components must map to valid function IDs and cover every function.')
