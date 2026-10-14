"use client";

import clsx from "clsx";
import Markdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import type { ReactNode } from "react";

const BLOCK_MATH = /\\\[([\s\S]+?)\\\]/g;
const INLINE_MATH = /\\\(([\s\S]+?)\\\)/g;

/** Language models write maths as \( … \) and \[ … \], which remark-math does not
 *  recognise — it wants dollars. Without this the delimiters land on the page as
 *  literal backslashes and the formula reads as source code. */
export function normaliseMath(text: string): string {
  return (text ?? "")
    .replace(BLOCK_MATH, (_match, body: string) => `$$${body.trim()}$$`)
    .replace(INLINE_MATH, (_match, body: string) => `$${body.trim()}$`);
}

const PLUGINS = [remarkGfm, remarkMath];
const REHYPE = [[rehypeKatex, { throwOnError: false, strict: false }]] as never;

/** Model-written prose: markdown, tables and maths. */
export function RichText({
  children,
  className,
}: {
  children: string | null | undefined;
  className?: string;
}) {
  return (
    <div className={clsx("prose-tutor", className)}>
      <Markdown remarkPlugins={PLUGINS} rehypePlugins={REHYPE}>
        {normaliseMath(children ?? "")}
      </Markdown>
    </div>
  );
}

/** The same, for a single line that must stay inline — a card front, a question
 *  stem, an answer option. */
export function RichLine({
  children,
  className,
}: {
  children: string | null | undefined;
  className?: string;
}) {
  return (
    <span className={clsx("rich-line", className)}>
      <Markdown
        remarkPlugins={PLUGINS}
        rehypePlugins={REHYPE}
        components={{ p: ({ children: inner }: { children?: ReactNode }) => <>{inner}</> }}
      >
        {normaliseMath(children ?? "")}
      </Markdown>
    </span>
  );
}
