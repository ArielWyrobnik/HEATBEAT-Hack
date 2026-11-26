import katex from 'katex';
import 'katex/dist/katex.min.css';

/** Renders a LaTeX formula with KaTeX. `block` = display style on its own line. */
export default function Tex({ children, block = false }: { children: string; block?: boolean }) {
  const html = katex.renderToString(children, { displayMode: block, throwOnError: false, strict: false, output: 'html' });
  return block
    ? <div className="tex-block" dangerouslySetInnerHTML={{ __html: html }} />
    : <span className="tex" dangerouslySetInnerHTML={{ __html: html }} />;
}
