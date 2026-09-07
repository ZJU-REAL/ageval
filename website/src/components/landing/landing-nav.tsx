"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Languages } from "lucide-react";
import { OwlFlatIcon } from "@/components/owl-flat";
import type { SiteLocale } from "@/lib/i18n";
import { sitePath } from "@/lib/shared";
import type { LandingCopy } from "./copy";

type LandingNavProps = {
  lang: SiteLocale;
  copy: LandingCopy["nav"];
  navAria: string;
  repoUrl: string;
  hubUrl: string | null;
};

const sections = [
  ["problem", "problem"],
  ["position", "position"],
  ["environment", "environment"],
  ["eval", "eval"],
  ["plugin", "plugin"],
  ["faq", "faq"],
] as const;

const sectionIds = sections.map(([id]) => id);

export function LandingNav({
  lang,
  copy,
  navAria,
  repoUrl,
  hubUrl,
}: LandingNavProps) {
  const drawerRef = useRef<HTMLDetailsElement>(null);
  const otherLang = lang === "zh-CN" ? "en" : "zh-CN";
  const [active, setActive] = useState<string | null>(null);

  useEffect(() => {
    const spy = 80;
    let raf = 0;

    function update() {
      let current: string | null = null;
      for (const id of sectionIds) {
        const el = document.getElementById(id);
        if (!el) continue;
        if (el.getBoundingClientRect().top <= spy) current = id;
      }
      setActive((prev) => (prev === current ? prev : current));
    }

    function onScroll() {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        update();
      });
    }

    update();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("hashchange", update);
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("hashchange", update);
      if (raf) cancelAnimationFrame(raf);
    };
  }, []);

  function closeDrawer() {
    if (drawerRef.current) drawerRef.current.open = false;
  }

  return (
    <nav aria-label={navAria}>
      <div className="wrap nav-inner">
        <a className="logo" href="#top">
          <OwlFlatIcon className="nav-owl" />
          ageval<span>.</span>
        </a>
        <div className="nav-sections">
          {sections.map(([href, key]) => (
            <a
              key={key}
              href={`#${href}`}
              aria-current={active === href ? "location" : undefined}
            >
              {copy[key]}
            </a>
          ))}
        </div>
        <div className="nav-actions">
          <Link href={`/${lang}/docs`}>{copy.docs}</Link>
          {hubUrl ? (
            <a href={hubUrl} target="_blank" rel="noopener noreferrer">
              {copy.hub}
            </a>
          ) : null}
          <a href={repoUrl} rel="noopener noreferrer">
            {copy.repo}
          </a>
          <details ref={drawerRef} className="nav-drawer">
            <summary className="nav-drawer-btn">{copy.menu}</summary>
            <div className="nav-drawer-panel">
              {sections.map(([href, key]) => (
                <a
                  key={key}
                  href={`#${href}`}
                  aria-current={active === href ? "location" : undefined}
                  onClick={closeDrawer}
                >
                  {copy[key]}
                </a>
              ))}
              <div className="nav-drawer-split" />
              <Link href={`/${lang}/docs`} onClick={closeDrawer}>
                {copy.docs}
              </Link>
              {hubUrl ? (
                <a
                  href={hubUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={closeDrawer}
                >
                  {copy.hub}
                </a>
              ) : null}
              <a href={repoUrl} rel="noopener noreferrer" onClick={closeDrawer}>
                {copy.repo}
              </a>
              <a
                className="nav-lang"
                href={sitePath(`/${otherLang}`)}
                onClick={closeDrawer}
              >
                <Languages aria-hidden="true" />
                {copy.lang}
              </a>
            </div>
          </details>
          <a className="nav-lang" href={sitePath(`/${otherLang}`)}>
            <Languages aria-hidden="true" />
            {copy.lang}
          </a>
        </div>
      </div>
    </nav>
  );
}
