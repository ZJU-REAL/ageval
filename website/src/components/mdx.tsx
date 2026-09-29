import defaultMdxComponents from "fumadocs-ui/mdx";
import type { ImgHTMLAttributes } from "react";
import type { MDXComponents } from "mdx/types";
import { assetPath } from "@/lib/shared";
import { Mermaid } from "./mermaid";

function DocImage({ src, alt, ...rest }: ImgHTMLAttributes<HTMLImageElement>) {
  const resolved =
    typeof src === "string" && src.startsWith("/") && !src.startsWith("//")
      ? assetPath(src)
      : src;
  return <img {...rest} src={resolved} alt={alt ?? ""} />;
}

export function getMDXComponents(components?: MDXComponents) {
  return {
    ...defaultMdxComponents,
    img: DocImage,
    Mermaid,
    ...components,
  } satisfies MDXComponents;
}

export const useMDXComponents = getMDXComponents;

declare global {
  type MDXProvidedComponents = ReturnType<typeof getMDXComponents>;
}
