import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { BookOpen, Copyright, Orbit } from "lucide-react";
import { landingCopy } from "@/components/landing/copy";
import { LandingNav } from "@/components/landing/landing-nav";
import { HeroSignal } from "@/components/landing/hero-signal";
import { HeroRotate } from "@/components/landing/hero-rotate";
import { OwlPixelMark } from "@/components/landing/owl-pixel";
import { StartCode } from "@/components/landing/start-code";
import { CoreFlow } from "@/components/landing/core-flow";
import { DemoVideo } from "@/components/landing/demo-video";
import { isSiteLocale } from "@/lib/i18n";
import { gitConfig, hubSiteUrl, sitePath } from "@/lib/shared";

/** GitHub invertocat. Fill uses currentColor. Path matches hub `GitHubIcon`. */
function GitHubMark() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 1 100 97.53"
      fill="currentColor"
      aria-hidden="true"
    >
      <path d="M50 1C22.39 1 0 23.386 0 51c0 22.092 14.326 40.835 34.193 47.446 2.499.463 3.416-1.085 3.416-2.405 0-1.192-.046-5.132-.067-9.31-13.91 3.025-16.846-5.899-16.846-5.899-2.274-5.78-5.552-7.316-5.552-7.316-4.536-3.103.342-3.04.342-3.04 5.021.353 7.665 5.153 7.665 5.153 4.46 7.644 11.697 5.434 14.55 4.157.449-3.232 1.745-5.437 3.175-6.686-11.106-1.265-22.78-5.552-22.78-24.71 0-5.46 1.953-9.92 5.151-13.421-.519-1.26-2.23-6.345.485-13.232 0 0 4.198-1.344 13.753 5.125 3.988-1.108 8.266-1.663 12.515-1.682 4.25.018 8.53.574 12.526 1.682 9.543-6.47 13.736-5.125 13.736-5.125 2.722 6.887 1.01 11.972.49 13.232 3.206 3.501 5.146 7.961 5.146 13.42 0 19.204-11.697 23.433-22.83 24.67 1.793 1.553 3.39 4.596 3.39 9.26 0 6.69-.057 12.075-.057 13.722 0 1.33.9 2.89 3.434 2.398C85.691 91.82 100 73.085 100 51.001c0-27.615-22.386-50-50-50" />
    </svg>
  );
}

const repoUrl = `https://github.com/${gitConfig.user}/${gitConfig.repo}`;
const hubUrl = hubSiteUrl();

type HeroCtasDemo = {
  label: string;
  title: string;
  closeLabel: string;
};

function HeroCtas({
  repoLabel,
  hubLabel,
  docsLabel,
  docsHref,
  demo,
  line,
}: {
  repoLabel: string;
  hubLabel: string;
  docsLabel: string;
  docsHref: string;
  demo?: HeroCtasDemo;
  line?: boolean;
}) {
  const rest = line ? "btn btn-line" : "btn btn-ghost";
  return (
    <div className="hero-ctas">
      <a
        className={line ? "btn btn-line" : "btn btn-pri"}
        href={repoUrl}
        target="_blank"
        rel="noopener noreferrer"
      >
        <GitHubMark />
        {repoLabel}
      </a>
      {demo ? (
        <DemoVideo
          className={rest}
          label={demo.label}
          title={demo.title}
          closeLabel={demo.closeLabel}
        />
      ) : null}
      {hubUrl ? (
        <a
          className={rest}
          href={hubUrl}
          target="_blank"
          rel="noopener noreferrer"
        >
          <Orbit aria-hidden="true" />
          {hubLabel}
        </a>
      ) : null}
      <a className={rest} href={docsHref}>
        <BookOpen aria-hidden="true" />
        {docsLabel}
      </a>
    </div>
  );
}


/** Render one hero title line, highlighting its first `accent` occurrence. */
function AccentLine({ line, accent }: { line: string; accent: string }) {
  const i = line.indexOf(accent);
  if (i < 0) return line;
  return (
    <>
      {line.slice(0, i)}
      <span className="hero-title-accent">{accent}</span>
      {line.slice(i + accent.length)}
    </>
  );
}

type HomeParams = { lang: string };

export async function generateMetadata({
  params,
}: {
  params: Promise<HomeParams>;
}): Promise<Metadata> {
  const { lang } = await params;
  if (!isSiteLocale(lang)) return {};
  const text = landingCopy[lang];
  return {
    title: { absolute: text.metaTitle },
    description: text.metaDescription,
  };
}

export default async function HomePage({ params }: { params: Promise<HomeParams> }) {
  const { lang } = await params;
  if (!isSiteLocale(lang)) notFound();
  const text = landingCopy[lang];

  return (
    <div className="ageval-landing">
      <a className="skip" href="#main">
        {text.skip}
      </a>

      <LandingNav
        lang={lang}
        copy={text.nav}
        navAria={text.navAria}
        repoUrl={repoUrl}
        hubUrl={hubUrl}
      />

      <main id="main">
        <section className="hero" id="top">
          <HeroSignal />
          <div className="hero-grid" aria-hidden="true" />
          <OwlPixelMark className="owl-wash" />
          <div className="wrap-wide hero-stack">
            <div className="hero-center">
              <h1 className="hero-title">
                <span className="hero-title-a">
                  <AccentLine line={text.hero.titleA} accent={text.hero.accentA} />
                </span>
                <span className="hero-title-b">
                  <AccentLine line={text.hero.titleB} accent={text.hero.accentB} />
                </span>
                <HeroRotate />
              </h1>
              <p className="hero-note">{text.hero.note}</p>
              <HeroCtas
                line
                repoLabel={text.hero.primary}
                hubLabel={text.hero.hub}
                docsLabel={text.hero.secondary}
                docsHref={sitePath(`/${lang}/docs`)}
                demo={{
                  label: text.hero.demo,
                  title: text.hero.demoAria,
                  closeLabel: text.hero.demoClose,
                }}
              />
            </div>
            <div className="hero-foot">
              <aside className="stage" aria-label={text.hero.startAria}>
                <span className="cross tl" aria-hidden="true" />
                <span className="cross br" aria-hidden="true" />
                <StartCode
                  tabs={text.hero.startTabs}
                  copyLabel={text.hero.copy}
                  copiedLabel={text.hero.copied}
                />
              </aside>
            </div>
          </div>
        </section>

        <section className="pact" aria-label={text.pactAria}>
          <div className="wrap pact-inner">
            {text.pact.map(([en, zh, body]) => (
              <article key={en}>
                <p className="en">{en}</p>
                <p className="zh">{zh}</p>
                <p>{body}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="block" id="problem">
          <div className="wrap">
            <div className="sec-head">
              <span className="sec-index">{text.problem.index}</span>
              <span className="sec-name">{text.problem.name}</span>
            </div>
            <h2>
              {text.problem.title[0]}
              <br />
              {text.problem.title[1]}
            </h2>
            <div className="problem-grid">
              {text.problem.items.map(([k, title, body]) => (
                <article key={k}>
                  <p className="k">{k}</p>
                  <h3>{title}</h3>
                  <p>{body}</p>
                </article>
              ))}
            </div>
            <p className="sol">
              {text.problem.solLabel} <b>{text.problem.sol}</b>
            </p>
          </div>
        </section>

        <section className="block" id="position">
          <div className="wrap">
            <div className="sec-head">
              <span className="sec-index">{text.position.index}</span>
              <span className="sec-name">{text.position.name}</span>
            </div>
            <h2>{text.position.title}</h2>
            <p className="lead">{text.position.lead}</p>
            <CoreFlow copy={text.position.flow} />
          </div>
        </section>

        <section className="block" id="environment">
          <div className="wrap">
            <div className="sec-head">
              <span className="sec-index">{text.environment.index}</span>
              <span className="sec-name">{text.environment.name}</span>
            </div>
            <h2>{text.environment.title}</h2>
            <p className="lead">{text.environment.lead}</p>
            <div className="tiers">
              {text.environment.items.map(([st, title, body, tag, hot]) => (
                <article key={st} className={hot ? "hot" : undefined}>
                  <p className="st">{st}</p>
                  <h3>{title}</h3>
                  <p>{body}</p>
                  <p className="tag">{tag}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section className="block" id="eval">
          <div className="wrap">
            <div className="sec-head">
              <span className="sec-index">{text.eval.index}</span>
              <span className="sec-name">{text.eval.name}</span>
            </div>
            <h2>{text.eval.title}</h2>
            <p className="lead">{text.eval.lead}</p>
            <table className="skill-table">
              <caption>{text.eval.tableAria}</caption>
              <thead>
                <tr>
                  {text.eval.columns.map((col) => (
                    <th key={col} scope="col">
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {text.eval.skills.map(([name, body]) => (
                  <tr key={name}>
                    <th scope="row">
                      <code>{name}</code>
                    </th>
                    <td>{body}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <dl className="barrier-note skill-steps">
              {text.eval.steps.map(([dt, dd]) => (
                <div key={dt}>
                  <dt>{dt}</dt>
                  <dd>{dd}</dd>
                </div>
              ))}
            </dl>
          </div>
        </section>

        <section className="block" id="plugin">
          <div className="wrap">
            <div className="sec-head">
              <span className="sec-index">{text.plugin.index}</span>
              <span className="sec-name">{text.plugin.name}</span>
            </div>
            <h2>{text.plugin.title}</h2>
            <p className="lead">{text.plugin.lead}</p>
            <div className="slots">
              {text.plugin.slots.map(([lv, title, body]) => (
                <article key={title}>
                  <div className="lv">{lv}</div>
                  <h3>{title}</h3>
                  <p>{body}</p>
                </article>
              ))}
            </div>
            <div className="plugin-example">
              <div>
                <p className="duo-tag">{text.plugin.exampleTag}</p>
                <h3>{text.plugin.exampleTitle}</h3>
                <p>{text.plugin.exampleBody}</p>
              </div>
              <pre className="code-panel" tabIndex={0}>
                {text.plugin.exampleCode}
              </pre>
            </div>
          </div>
        </section>

        <section className="block" id="faq">
          <div className="wrap">
            <div className="sec-head">
              <span className="sec-index">{text.faq.index}</span>
              <span className="sec-name">{text.faq.name}</span>
            </div>
            <h2>{text.faq.title}</h2>
            <div className="faq-list">
              {text.faq.items.map(([question, paragraphs]) => (
                <details key={question} className="faq-item">
                  <summary className="faq-q">{question}</summary>
                  <div className="faq-panel">
                    <div className="faq-a">
                      {paragraphs.map((p) => (
                        <p key={p.slice(0, 48)}>{p}</p>
                      ))}
                    </div>
                  </div>
                </details>
              ))}
            </div>
          </div>
        </section>

        <section className="cta-band">
          <div className="wrap">
            <h2>
              {text.cta.title[0]}
              <br />
              {text.cta.title[1]}
            </h2>
            <HeroCtas
              line
              repoLabel={text.cta.primary}
              hubLabel={text.cta.hub}
              docsLabel={text.cta.docs}
              docsHref={sitePath(`/${lang}/docs`)}
              demo={{
                label: text.hero.demo,
                title: text.hero.demoAria,
                closeLabel: text.hero.demoClose,
              }}
            />
          </div>
        </section>
      </main>

      <footer>
        <div className="wrap foot">
          <a className="logo" href="#top">
            ageval<span>.</span>
          </a>
          <p className="foot-copy">
            <Copyright aria-hidden="true" />
            {text.footer.copy}
          </p>
        </div>
      </footer>
    </div>
  );
}
