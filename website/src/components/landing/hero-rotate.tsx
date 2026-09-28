import { ENVIRONMENTS, HARNESSES, type Harness } from "./harness-marks";

const ITEMS: readonly Harness[] = [...HARNESSES, ...ENVIRONMENTS];

function HarnessItem({ harness }: { harness: Harness }) {
  return (
    <span className="hero-rotate-item">
      <span className="hero-rotate-icon">
        {"src" in harness ? (
          <img
            src={harness.src}
            alt=""
            width={24}
            height={24}
            draggable={false}
            className="hero-rotate-mark"
            data-mark={harness.id}
          />
        ) : (
          <harness.Mark className="hero-rotate-mark" />
        )}
      </span>
      <span className="hero-rotate-name">{harness.name}</span>
    </span>
  );
}

/**
 * Marquee row of harness marks (icon + name). The set renders twice and
 * the track translates by exactly one set width, so the loop is
 * seamless. Pure CSS; reduced motion leaves the row static.
 */
export function HeroRotate() {
  return (
    <span className="hero-rotate" aria-hidden="true">
      <span className="hero-rotate-track">
        {[0, 1].map((set) => (
          <span className="hero-rotate-set" key={set}>
            {ITEMS.map((harness) => (
              <HarnessItem key={harness.id} harness={harness} />
            ))}
          </span>
        ))}
      </span>
    </span>
  );
}
