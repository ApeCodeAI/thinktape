import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { Wikilink, type WikilinkKind, splitWikilinks } from "./Wikilink";

interface Props {
  children: string;
  onWikilinkClick: (target: string, kind: WikilinkKind) => void;
}

/**
 * Markdown renderer that turns [[wikilinks]] into clickable pills.
 *
 * Implementation: intercepts every text node and splits it on [[…]] using a
 * regex. Code blocks render via the `code` component path and are left intact.
 */
export function Markdown({ children, onWikilinkClick }: Props) {
  const renderText = (value: string) => {
    const parts = splitWikilinks(value);
    if (parts.length <= 1 && parts[0]?.kind === "text") {
      return parts[0].value;
    }
    return parts.map((p, i) =>
      p.kind === "text" ? (
        <React.Fragment key={i}>{p.value}</React.Fragment>
      ) : (
        <Wikilink
          key={i}
          target={p.target}
          kind={p.type}
          onClick={onWikilinkClick}
        />
      ),
    );
  };

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        // react-markdown 9 renders text nodes via React.createElement('text', ...) when there is no node mapping.
        // Use the documented escape hatch: override text via the components prop is not directly supported,
        // so we instead transform via children walking. Achieve the same result by overriding the most
        // common containers and recursing through their `children` to handle text segments.
        p: ({ children }) => <p>{walkChildren(children, renderText)}</p>,
        li: ({ children }) => <li>{walkChildren(children, renderText)}</li>,
        h1: ({ children }) => <h1>{walkChildren(children, renderText)}</h1>,
        h2: ({ children }) => <h2>{walkChildren(children, renderText)}</h2>,
        h3: ({ children }) => <h3>{walkChildren(children, renderText)}</h3>,
        h4: ({ children }) => <h4>{walkChildren(children, renderText)}</h4>,
        em: ({ children }) => <em>{walkChildren(children, renderText)}</em>,
        strong: ({ children }) => <strong>{walkChildren(children, renderText)}</strong>,
        blockquote: ({ children }) => <blockquote>{walkChildren(children, renderText)}</blockquote>,
        td: ({ children }) => <td>{walkChildren(children, renderText)}</td>,
        th: ({ children }) => <th>{walkChildren(children, renderText)}</th>,
      }}
    >
      {children}
    </ReactMarkdown>
  );
}

function walkChildren(
  children: React.ReactNode,
  renderText: (s: string) => React.ReactNode,
): React.ReactNode {
  return React.Children.map(children, (child, idx) => {
    if (typeof child === "string") {
      return <React.Fragment key={idx}>{renderText(child)}</React.Fragment>;
    }
    if (typeof child === "number") {
      return child;
    }
    if (Array.isArray(child)) {
      return walkChildren(child, renderText);
    }
    return child;
  });
}
