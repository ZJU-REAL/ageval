import { createContext, useContext, useEffect, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { BreadcrumbNav, type Crumb } from "@ageval/shared/components/breadcrumb";

type PageHeadProps = {
  title: ReactNode;
  sub?: ReactNode;
  actions?: ReactNode;
};

const PageHeadSlotContext = createContext<HTMLElement | null>(null);

export function PageHeadSlotProvider({
  slot,
  children,
}: {
  slot: HTMLElement | null;
  children: ReactNode;
}) {
  return (
    <PageHeadSlotContext.Provider value={slot}>
      {children}
    </PageHeadSlotContext.Provider>
  );
}

/** Registers the page title into the shell header (two compact lines). */
export function PageHead({ title, sub, actions }: PageHeadProps) {
  const slot = useContext(PageHeadSlotContext);
  const text = typeof title === "string" ? title : null;

  useEffect(() => {
    if (!text) return;
    const previous = document.title;
    document.title = `${text} · ageval Hub`;
    return () => {
      document.title = previous;
    };
  }, [text]);

  if (!slot) return null;

  return (
    <>
      <h1 className="sr-only">{text ?? title}</h1>
      {createPortal(
        <div className="flex min-w-0 flex-1 items-center gap-3">
          <div className="min-w-0">
            <p
              aria-hidden
              className="truncate text-lg font-semibold leading-6 tracking-tight text-ink"
            >
              {title}
            </p>
            {sub ? (
              <div className="mt-1 min-w-0 text-[13px] leading-4 text-body">
                {sub}
              </div>
            ) : null}
          </div>
          {actions ? (
            <div className="flex shrink-0 items-center gap-2">{actions}</div>
          ) : null}
        </div>,
        slot,
      )}
    </>
  );
}

/** List-section title + trail in the shell header (detail pages). */
export function CatalogHead({
  title,
  crumbs,
}: {
  title: string;
  crumbs: Crumb[];
}) {
  return (
    <PageHead
      title={title}
      sub={
        <BreadcrumbNav
          items={crumbs}
          className="flex-nowrap overflow-hidden text-[13px] leading-4"
        />
      }
    />
  );
}
