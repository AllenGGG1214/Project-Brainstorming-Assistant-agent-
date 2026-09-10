import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Idea Atelier · Project Planning Workspace',
  description: 'Turn an idea into an evidence-backed, scoped, and buildable project.',
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}
