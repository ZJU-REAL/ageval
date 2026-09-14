/**
 * Lightweight shell-command highlighting for CLI strips.
 * Not a full parser — tokenizes flags, strings, paths, and words.
 */
import type { ReactNode } from "react";

type Kind = "cmd" | "flag" | "string" | "path" | "punct" | "plain";

type Token = { kind: Kind; text: string };

const KIND_CLASS: Record<Kind, string> = {
  cmd: "text-shell-cmd",
  flag: "text-shell-flag",
  string: "text-shell-string",
  path: "text-shell-path",
  punct: "text-shell-punct",
  plain: "text-shell-plain",
};

function tokenizeShell(command: string): Token[] {
  const tokens: Token[] = [];
  let i = 0;
  let wordIndex = 0;

  while (i < command.length) {
    const ch = command[i];

    // whitespace
    if (/\s/.test(ch)) {
      let j = i + 1;
      while (j < command.length && /\s/.test(command[j])) j += 1;
      tokens.push({ kind: "plain", text: command.slice(i, j) });
      i = j;
      continue;
    }

    // quoted string
    if (ch === "'" || ch === '"') {
      const quote = ch;
      let j = i + 1;
      while (j < command.length && command[j] !== quote) {
        if (command[j] === "\\" && quote === '"') j += 1;
        j += 1;
      }
      if (j < command.length) j += 1;
      tokens.push({ kind: "string", text: command.slice(i, j) });
      i = j;
      wordIndex += 1;
      continue;
    }

    // unquoted token
    let j = i;
    while (j < command.length && !/\s/.test(command[j])) j += 1;
    const text = command.slice(i, j);
    let kind: Kind = "plain";
    if (wordIndex === 0) {
      kind = "cmd";
    } else if (text.startsWith("-")) {
      kind = "flag";
    } else if (
      text.includes("/") ||
      text.startsWith(".") ||
      text.startsWith("~")
    ) {
      kind = "path";
    } else if (/^[=<>|&;]+$/.test(text)) {
      kind = "punct";
    } else {
      kind = "plain";
    }
    tokens.push({ kind, text });
    i = j;
    wordIndex += 1;
  }

  return tokens;
}

export function ShellCode({ command }: { command: string }): ReactNode {
  const tokens = tokenizeShell(command);
  return (
    <>
      {tokens.map((t, idx) => (
        <span key={`${idx}-${t.kind}`} className={KIND_CLASS[t.kind]}>
          {t.text}
        </span>
      ))}
    </>
  );
}
