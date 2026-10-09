import type { DesignSystem, Page, SlideMeta } from '@open-slide/core';

import irfanV3 from './assets/irfan_v3_cut.png';
import standaloneImg from './assets/standalone.png';
import videoThumb from './assets/video_thumb.jpg';
import savhSession1 from './assets/session1_raw.png';
import savhSession2 from './assets/session2.png';
import savhSession3 from './assets/session3.png';
import bemyEyesImg from './assets/bemyeyes.jpg';
import envisionImg from './assets/envision.jpg';
import orcamImg from './assets/orcam.png';
import asiriveLogo from './assets/asirive-logo.svg';

// ─── Webfonts (loaded once per slide id) ─────────────────────────────────────
const FONT_HREF =
  'https://fonts.googleapis.com/css2?family=Anton&family=Space+Grotesk:wght@400;500;700&family=Space+Mono:wght@400;700&display=swap';
const FONT_LINK_ID = 'osd-webfont-cortex-ivp';
if (typeof document !== 'undefined' && !document.getElementById(FONT_LINK_ID)) {
  const link = document.createElement('link');
  link.id = FONT_LINK_ID;
  link.rel = 'stylesheet';
  link.href = FONT_HREF;
  document.head.appendChild(link);
}

// ─── Design tokens ───────────────────────────────────────────────────────────
export const design: DesignSystem = {
  palette: {
    bg: '#0A0A08',
    text: '#F4F4EC',
    accent: '#D8E516',
  },
  fonts: {
    display: '"Anton", "Arial Narrow", sans-serif',
    body: '"Space Grotesk", "Inter", system-ui, sans-serif',
  },
  typeScale: {
    hero: 210,
    body: 34,
  },
  radius: 4,
};

const palette = {
  bg: design.palette.bg,
  text: design.palette.text,
  accent: design.palette.accent,
  muted: '#8B8B7E',
  dim: 'rgba(244,244,236,0.38)',
  line: 'rgba(244,244,236,0.16)',
  lineSoft: 'rgba(244,244,236,0.09)',
  surface: '#131309',
  surfaceHi: '#1B1B10',
};

const font = {
  display: design.fonts.display,
  body: design.fonts.body,
  mono: '"Space Mono", ui-monospace, Menlo, monospace',
};

const fill: React.CSSProperties = {
  width: '100%',
  height: '100%',
  background: 'var(--osd-bg)',
  color: 'var(--osd-text)',
  fontFamily: 'var(--osd-font-body)',
  overflow: 'hidden',
  position: 'relative',
};

const styles = `
  @keyframes cx-fadeUp {
    from { opacity: 0; transform: translateY(18px); }
    to   { opacity: 1; transform: translateY(0); }
  }
  .cx-up { opacity: 0; animation: cx-fadeUp 0.8s cubic-bezier(.2,.7,.2,1) forwards; }
`;

const Styles = () => <style>{styles}</style>;

// ─── Shared chrome ───────────────────────────────────────────────────────────
const Chrome = ({
  right = 'IVP 2026 // USER-FIRST OR USER-FAIL?',
}: {
  right?: string;
}) => (
  <div
    style={{
      position: 'absolute',
      top: 44,
      left: 100,
      right: 100,
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
    }}
  >
    <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
      <img
        src={asiriveLogo}
        alt="Asirive"
        style={{ width: 38, height: 38, display: 'block' }}
      />
      <Brand />
    </div>
    <span
      style={{
        fontFamily: font.mono,
        fontSize: 16,
        letterSpacing: '0.14em',
        color: palette.dim,
      }}
    >
      {right}
    </span>
  </div>
);

const Brand = ({ size = 19 }: { size?: number }) => (
  <span
    style={{
      fontFamily: font.mono,
      fontSize: size,
      letterSpacing: '0.14em',
    }}
  >
    <span style={{ color: palette.text }}>ASIRIVE</span>{' '}
    <span style={{ color: 'var(--osd-accent)' }}>CORTEX</span>
  </span>
);

const Tag = ({
  children,
  color = palette.muted,
  style,
}: {
  children: React.ReactNode;
  color?: string;
  style?: React.CSSProperties;
}) => (
  <div
    style={{
      fontFamily: font.mono,
      fontSize: 19,
      letterSpacing: '0.16em',
      textTransform: 'uppercase',
      color,
      ...style,
    }}
  >
    {children}
  </div>
);

const Rule = ({ style }: { style?: React.CSSProperties }) => (
  <div style={{ height: 1, background: palette.line, width: '100%', ...style }} />
);

const Halftone = ({
  style,
  color = 'rgba(216,229,22,0.4)',
}: {
  style?: React.CSSProperties;
  color?: string;
}) => (
  <div
    style={{
      position: 'absolute',
      backgroundImage: `radial-gradient(circle, ${color} 2px, transparent 2px)`,
      backgroundSize: '20px 20px',
      pointerEvents: 'none',
      ...style,
    }}
  />
);

const Rings = ({
  size = 620,
  style,
}: {
  size?: number;
  style?: React.CSSProperties;
}) => (
  <div style={{ position: 'absolute', width: size, height: size, ...style }}>
    {[0, 1, 2, 3, 4].map((i) => (
      <div
        key={i}
        style={{
          position: 'absolute',
          inset: i * 62,
          border: `1px solid rgba(244,244,236,0.10)`,
          borderRadius: '50%',
        }}
      />
    ))}
  </div>
);

const Checker = ({ style }: { style?: React.CSSProperties }) => (
  <div style={{ position: 'absolute', display: 'flex', gap: 10, ...style }}>
    {[0, 1, 2, 3, 4, 5].map((i) => (
      <div
        key={i}
        style={{
          width: 18,
          height: 18,
          background: i % 2 === 0 ? 'var(--osd-accent)' : 'transparent',
          border: i % 2 === 0 ? 'none' : `1px solid ${palette.line}`,
        }}
      />
    ))}
  </div>
);

// ─── Design-thinking loop rail ───────────────────────────────────────────────
const STAGES = [
  { n: '01', name: 'EMPATHIZE' },
  { n: '02', name: 'DEFINE' },
  { n: '03', name: 'RESEARCH' },
  { n: '04', name: 'IDEATE' },
  { n: '05', name: 'PROTOTYPE' },
  { n: '06', name: 'TEST' },
];

const LoopRail = ({ active }: { active: number }) => (
  <div style={{ position: 'relative', width: '100%' }}>
    {/* connecting line */}
    <div
      style={{
        position: 'absolute',
        top: 27,
        left: 90,
        right: 90,
        height: 2,
        background: palette.line,
      }}
    />
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        position: 'relative',
      }}
    >
      {STAGES.map((s, i) => {
        const isActive = i === active;
        const isPast = i < active;
        return (
          <div
            key={s.n}
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: 14,
              width: 200,
            }}
          >
            <div
              style={{
                width: 56,
                height: 56,
                borderRadius: '50%',
                background: isActive
                  ? 'var(--osd-accent)'
                  : isPast
                    ? 'rgba(216,229,22,0.16)'
                    : palette.bg,
                border: isActive
                  ? '2px solid var(--osd-accent)'
                  : `2px solid ${isPast ? 'rgba(216,229,22,0.5)' : palette.line}`,
                display: 'grid',
                placeItems: 'center',
                fontFamily: font.mono,
                fontSize: 20,
                color: isActive ? palette.bg : isPast ? palette.accent : palette.muted,
              }}
            >
              {s.n}
            </div>
            <span
              style={{
                fontFamily: font.mono,
                fontSize: 17,
                letterSpacing: '0.12em',
                color: isActive ? palette.text : palette.muted,
              }}
            >
              {s.name}
            </span>
          </div>
        );
      })}
    </div>
    {/* loop-back path */}
    <div
      style={{
        position: 'absolute',
        top: 55,
        left: 90,
        right: 90,
        height: 52,
        borderLeft: `2px solid ${palette.line}`,
        borderRight: `2px solid ${palette.line}`,
        borderBottom: `2px solid ${palette.line}`,
        borderBottomLeftRadius: 26,
        borderBottomRightRadius: 26,
      }}
    />
    <div
      style={{
        position: 'absolute',
        top: 40,
        left: 78,
        width: 0,
        height: 0,
        borderLeft: '7px solid transparent',
        borderRight: '7px solid transparent',
        borderBottom: `16px solid ${palette.line}`,
      }}
    />
    <div
      style={{
        position: 'absolute',
        left: 0,
        right: 0,
        top: 118,
        textAlign: 'center',
      }}
    >
      <span
        style={{
          fontFamily: font.mono,
          fontSize: 16,
          letterSpacing: '0.16em',
          color: palette.dim,
          background: palette.bg,
          padding: '0 18px',
        }}
      >
        EVERY TEST LOOPS BACK — WE ITERATE
      </span>
    </div>
  </div>
);

// ─── Chapter divider (explicit instances, one per stage) ─────────────────────
const StageDivider: Page = ({
  stageIndex,
  question,
}: {
  stageIndex: number;
  question: string;
}) => (
  <div style={fill}>
    <Styles />
    <Chrome />
    <Halftone
      style={{
        right: 100,
        top: 150,
        width: 300,
        height: 110,
        maskImage: 'linear-gradient(105deg, black 30%, transparent 90%)',
        WebkitMaskImage: 'linear-gradient(105deg, black 30%, transparent 90%)',
      }}
    />
    <div
      style={{
        position: 'absolute',
        inset: 0,
        padding: '150px 100px 130px',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 70 }}>
        <div
          style={{
            fontFamily: 'var(--osd-font-display)',
            fontSize: 330,
            lineHeight: 0.85,
            color: 'transparent',
            WebkitTextStroke: `3px ${palette.accent}`,
          }}
        >
          {STAGES[stageIndex].n}
        </div>
        <div style={{ paddingTop: 34, flex: 1 }}>
          <Tag color="var(--osd-accent)">STAGE {STAGES[stageIndex].n} // DESIGN THINKING</Tag>
          <h2
            style={{
              fontFamily: 'var(--osd-font-display)',
              fontSize: 128,
              lineHeight: 0.95,
              margin: '18px 0 0',
              letterSpacing: '0.005em',
            }}
          >
            {STAGES[stageIndex].name}
          </h2>
          <p
            style={{
              margin: '34px 0 0',
              fontSize: 38,
              lineHeight: 1.35,
              color: palette.muted,
              maxWidth: 1050,
            }}
          >
            {question}
          </p>
        </div>
      </div>
      <div style={{ marginTop: 'auto' }}>
        <LoopRail active={stageIndex} />
      </div>
    </div>
  </div>
);

// ─── Page 1 · Cover ──────────────────────────────────────────────────────────
const Cover: Page = () => (
  <div style={fill}>
    <Styles />
    <Rings size={760} style={{ left: -230, bottom: -260 }} />
    <Halftone
      style={{
        right: 100,
        top: 170,
        width: 420,
        height: 150,
        maskImage: 'linear-gradient(100deg, black 20%, transparent 95%)',
        WebkitMaskImage: 'linear-gradient(100deg, black 20%, transparent 95%)',
      }}
    />
    <Checker style={{ right: 100, bottom: 210 }} />
    <div
      style={{
        position: 'absolute',
        top: 44,
        left: 100,
        right: 100,
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
        <img
          src={asiriveLogo}
          alt="Asirive"
          style={{ width: 38, height: 38, display: 'block' }}
        />
        <Brand />
      </div>
      <span
        style={{
          fontFamily: font.mono,
          fontSize: 16,
          letterSpacing: '0.14em',
          color: palette.dim,
        }}
      >
        MOE INNOVATION PROGRAMME 2026
      </span>
    </div>

    <div
      style={{
        position: 'absolute',
        inset: 0,
        padding: '120px 100px 90px',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
      }}
    >
      <div className="cx-up" style={{ animationDelay: '0.1s' }}>
        <span
          style={{
            fontFamily: font.mono,
            fontSize: 21,
            letterSpacing: '0.18em',
            color: palette.bg,
            background: 'var(--osd-accent)',
            padding: '10px 20px',
          }}
        >
          IVP 2026 // CHALLENGE #1 — USER-FIRST OR USER-FAIL?
        </span>
      </div>
      <h1
        className="cx-up"
        style={{
          fontFamily: 'var(--osd-font-display)',
          fontSize: 'var(--osd-size-hero)',
          lineHeight: 0.92,
          margin: '48px 0 0',
          letterSpacing: '0.005em',
          animationDelay: '0.25s',
        }}
      >
        ASIRIVE
        <br />
        <span style={{ color: 'var(--osd-accent)' }}>CORTEX</span>
      </h1>
      <p
        className="cx-up"
        style={{
          margin: '40px 0 0',
          fontSize: 40,
          lineHeight: 1.3,
          color: palette.muted,
          maxWidth: 980,
          animationDelay: '0.4s',
        }}
      >
        Hands-free navigation for the visually impaired —{' '}
        <span style={{ color: palette.text }}>one voice, no screen, cane still in hand.</span>
      </p>
    </div>

    <div
      className="cx-up"
      style={{
        position: 'absolute',
        left: 100,
        right: 100,
        bottom: 60,
        display: 'flex',
        justifyContent: 'space-between',
        borderTop: `1px solid ${palette.line}`,
        paddingTop: 24,
        fontFamily: font.mono,
        fontSize: 17,
        letterSpacing: '0.12em',
        color: palette.muted,
        animationDelay: '0.55s',
      }}
    >
      <span>
        HAZIQ SHAH · MUHAMMAD IRFAN NUAFAL · ERYNA NATASHA — ADMIRALTY SECONDARY SCHOOL
      </span>
      <span style={{ color: palette.dim }}>WITH SAVH</span>
    </div>
  </div>
);

// ─── Page 2 · Contents ───────────────────────────────────────────────────────
const Contents: Page = () => {
  const rows = [
    { n: '01', name: 'THE CHALLENGE', note: 'user-first, and the CARE test' },
    { n: '02', name: 'STAGE 1 — EMPATHIZE', note: 'who we design for' },
    { n: '03', name: 'STAGE 2 — DEFINE', note: 'the problem we chose' },
    { n: '04', name: 'STAGE 3 — MARKET RESEARCH', note: 'what exists, what misses' },
    { n: '05', name: 'STAGE 4 — IDEATE', note: 'three design rules' },
    { n: '06', name: 'STAGE 5 — PROTOTYPE', note: 'what we built & how it works' },
    { n: '07', name: 'STAGE 6 — TEST', note: 'the failure that fixed it' },
    { n: '08', name: 'REFLECTION', note: 'proof · roadmap · what comes next' },
    { n: '09', name: 'SEE IT WORK', note: 'video showcase' },
    { n: '10', name: 'WITH THANKS', note: 'mentors who guided us' },
  ];
  return (
    <div style={fill}>
      <Styles />
      <Chrome right="CONTENTS //" />
      <Halftone
        style={{
          right: 100,
          bottom: 90,
          width: 260,
          height: 90,
          maskImage: 'linear-gradient(100deg, black 20%, transparent 95%)',
          WebkitMaskImage: 'linear-gradient(100deg, black 20%, transparent 95%)',
        }}
      />
      <div
        style={{
          position: 'absolute',
          inset: 0,
          padding: '150px 100px 110px',
          display: 'flex',
          gap: 90,
        }}
      >
        <div style={{ width: 480, flexShrink: 0 }}>
          <Tag color="var(--osd-accent)">// CONTENTS</Tag>
          <h2
            style={{
              fontFamily: 'var(--osd-font-display)',
              fontSize: 96,
              lineHeight: 0.96,
              margin: '22px 0 0',
            }}
          >
            WHAT'S
            <br />
            AHEAD
          </h2>
          <p
            style={{
              marginTop: 30,
              fontSize: 26,
              lineHeight: 1.45,
              color: palette.muted,
            }}
          >
            Design thinking is a loop, not a line. We followed six stages — and doubled
            back whenever testing proved us wrong.
          </p>
        </div>
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
          {rows.map((r, i) => (
            <div key={r.n}>
              <Rule />
              <div
                style={{
                  display: 'flex',
                  alignItems: 'baseline',
                  gap: 30,
                  padding: '21px 0',
                }}
              >
                <span
                  style={{
                    fontFamily: font.mono,
                    fontSize: 22,
                    color: 'var(--osd-accent)',
                  }}
                >
                  {r.n}
                </span>
                <span
                  style={{
                    fontFamily: font.body,
                    fontWeight: 700,
                    fontSize: 31,
                    letterSpacing: '0.01em',
                  }}
                >
                  {r.name}
                </span>
                <span
                  style={{
                    marginLeft: 'auto',
                    fontFamily: font.mono,
                    fontSize: 18,
                    color: palette.dim,
                  }}
                >
                  {r.note}
                </span>
              </div>
              {i === rows.length - 1 && <Rule />}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

// ─── Page 3 · The Challenge ──────────────────────────────────────────────────
const Challenge: Page = () => {
  const care = [
    { l: 'C', t: 'CARE FOR THE USER', d: 'does it meet real needs, values, preferences?' },
    { l: 'A', t: 'ACHIEVE ITS GOAL', d: 'does it solve the problem better than what exists?' },
    { l: 'R', t: 'RESPECT BROADER IMPACT', d: 'is it responsible to society and cost?' },
    { l: 'E', t: 'ENHANCE LIVES', d: 'does daily life get genuinely better?' },
  ];
  return (
    <div style={fill}>
      <Styles />
      <Chrome />
      <div
        style={{
          position: 'absolute',
          inset: 0,
          padding: '160px 100px 110px',
          display: 'flex',
          gap: 80,
        }}
      >
        <div style={{ width: 880, flexShrink: 0 }}>
          <Tag color="var(--osd-accent)">// THE CHALLENGE WE CHOSE</Tag>
          <h2
            style={{
              fontFamily: 'var(--osd-font-display)',
              fontSize: 122,
              lineHeight: 0.95,
              margin: '26px 0 0',
            }}
          >
            USER-FIRST,
            <br />
            <span style={{ color: 'var(--osd-accent)' }}>NEVER</span>{' '}
            <span style={{ color: palette.dim }}>USER-FAIL.</span>
          </h2>
          <p
            style={{
              margin: '36px 0 0',
              fontSize: 30,
              lineHeight: 1.45,
              color: palette.muted,
              maxWidth: 800,
            }}
          >
            IvP 2026 Challenge #1 asks one question:{' '}
            <span style={{ color: palette.text }}>
              does your design keep the user at the heart of everything?
            </span>{' '}
            assistive tech has a long history of user-fail — powerful devices nobody
            actually uses. we held Cortex to that standard from day one.
          </p>
        </div>
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
          <Tag>OUR YARDSTICK — THE CARE TEST</Tag>
          <div style={{ marginTop: 26 }}>
            {care.map((c, i) => (
              <div
                key={c.l}
                style={{
                  display: 'flex',
                  gap: 28,
                  alignItems: 'flex-start',
                  padding: '24px 0',
                  borderTop: i === 0 ? `1px solid ${palette.line}` : 'none',
                  borderBottom: `1px solid ${palette.line}`,
                }}
              >
                <span
                  style={{
                    fontFamily: 'var(--osd-font-display)',
                    fontSize: 58,
                    lineHeight: 1,
                    color: 'var(--osd-accent)',
                    width: 54,
                  }}
                >
                  {c.l}
                </span>
                <div>
                  <div style={{ fontWeight: 700, fontSize: 27, letterSpacing: '0.02em' }}>
                    {c.t}
                  </div>
                  <div
                    style={{
                      marginTop: 6,
                      fontSize: 22,
                      color: palette.muted,
                      lineHeight: 1.35,
                    }}
                  >
                    {c.d}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

// ─── Page 4 · Divider: Empathize ─────────────────────────────────────────────
const DividerEmpathize: Page = () => (
  <StageDivider
    stageIndex={0}
    question="Who are we designing for — and what does getting around actually feel like for them?"
  />
);

// ─── Page 5 · 2.2 billion ────────────────────────────────────────────────────
const BillionStat: Page = () => (
  <div style={fill}>
    <Styles />
    <Chrome />
    <Rings size={560} style={{ right: -180, top: -200 }} />
    <div
      style={{
        position: 'absolute',
        inset: 0,
        padding: '170px 100px 110px',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <Tag color="var(--osd-accent)">// STAGE 01 EMPATHIZE — THE SCALE</Tag>
      <h2
        style={{
          fontFamily: 'var(--osd-font-display)',
          fontSize: 200,
          lineHeight: 0.95,
          margin: '30px 0 0',
          color: 'var(--osd-accent)',
        }}
      >
        2.2 BILLION
      </h2>
      <p style={{ margin: '18px 0 0', fontSize: 36, lineHeight: 1.4, maxWidth: 1100 }}>
        people worldwide live with some form of vision impairment.
      </p>

      {/* readable bar: 9 in 10 */}
      <div style={{ marginTop: 64 }}>
        <div style={{ display: 'flex', gap: 12 }}>
          {[0, 1, 2, 3, 4, 5, 6, 7, 8].map((i) => (
            <div
              key={i}
              style={{
                flex: 1,
                height: 88,
                background: 'var(--osd-accent)',
                display: 'grid',
                placeItems: 'center',
                color: palette.bg,
                fontFamily: font.mono,
                fontSize: 19,
                letterSpacing: '0.08em',
              }}
            >
              {i === 4 ? '9 IN 10' : ''}
            </div>
          ))}
          <div
            style={{
              flex: 1,
              height: 88,
              border: `2px dashed ${palette.line}`,
              display: 'grid',
              placeItems: 'center',
              color: palette.dim,
              fontFamily: font.mono,
              fontSize: 19,
            }}
          >
            1
          </div>
        </div>
        <div
          style={{
            marginTop: 18,
            display: 'flex',
            justifyContent: 'space-between',
            fontFamily: font.mono,
            fontSize: 19,
            color: palette.muted,
          }}
        >
          <span>■ LIVE IN LOW- AND MIDDLE-INCOME COUNTRIES</span>
          <span>□ HIGH-INCOME COUNTRIES</span>
        </div>
      </div>

      <p
        style={{
          margin: '52px 0 0',
          fontSize: 30,
          lineHeight: 1.45,
          color: palette.muted,
          maxWidth: 1150,
        }}
      >
        Yet most assistive technology is designed — and priced — for the{' '}
        <span style={{ color: palette.text }}>1 in 10 who can pay.</span> that mismatch is
        where our project begins.
      </p>

      <div style={{ marginTop: 'auto' }}>
        <Rule />
        <div
          style={{
            marginTop: 18,
            fontFamily: font.mono,
            fontSize: 16,
            letterSpacing: '0.1em',
            color: palette.dim,
          }}
        >
          SOURCES: WORLD HEALTH ORGANIZATION FACT SHEET (2023) // IAPB VISION ATLAS
        </div>
      </div>
    </div>
  </div>
);

// ─── Page 6 · SAVH field research ────────────────────────────────────────────
const SavhResearch: Page = () => {
  const sessions = [
    { src: savhSession1, cap: '> SESSION 01 — ONLINE INTERVIEW', note: 'daily routines & pain points' },
    { src: savhSession2, cap: '> SESSION 02 — SAVH CENTRE VISIT', note: 'guided interviews with members' },
    { src: savhSession3, cap: '> SESSION 03 — NAVIGATION WALK', note: 'we followed, they led' },
  ];
  return (
    <div style={fill}>
      <Styles />
      <Chrome />
      <div
        style={{
          position: 'absolute',
          inset: 0,
          padding: '150px 100px 100px',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <Tag color="var(--osd-accent)">// STAGE 01 EMPATHIZE — PRIMARY RESEARCH</Tag>
        <h2
          style={{
            fontFamily: 'var(--osd-font-display)',
            fontSize: 92,
            lineHeight: 0.98,
            margin: '22px 0 40px',
            maxWidth: 1400,
          }}
        >
          WE DID NOT JUST RESEARCH ONLINE.
        </h2>
        <div style={{ display: 'flex', gap: 40, flex: 1, minHeight: 0 }}>
          {sessions.map((s, i) => (
            <div
              key={s.cap}
              style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 18 }}
            >
              <div
                style={{
                  position: 'relative',
                  flex: 1,
                  minHeight: 0,
                  border: `1px solid ${palette.line}`,
                  overflow: 'hidden',
                }}
              >
                <img
                  src={s.src}
                  alt={s.cap}
                  style={{
                    width: '100%',
                    height: '100%',
                    objectFit: 'cover',
                    objectPosition: i === 0 ? 'center 30%' : i === 1 ? '80% center' : 'center',
                    filter: 'grayscale(0.55) contrast(1.05)',
                    clipPath: i === 0 ? 'inset(6% 0 8% 0)' : undefined,
                    transform: i === 0 ? 'scale(1.16)' : undefined,
                  }}
                />
                <div
                  style={{
                    position: 'absolute',
                    top: 14,
                    left: 14,
                    width: 26,
                    height: 26,
                    borderLeft: `3px solid var(--osd-accent)`,
                    borderTop: `3px solid var(--osd-accent)`,
                  }}
                />
                <div
                  style={{
                    position: 'absolute',
                    bottom: 14,
                    right: 14,
                    width: 26,
                    height: 26,
                    borderRight: `3px solid var(--osd-accent)`,
                    borderBottom: `3px solid var(--osd-accent)`,
                  }}
                />
              </div>
              <div>
                <div
                  style={{
                    fontFamily: font.mono,
                    fontSize: 18,
                    letterSpacing: '0.1em',
                    color: 'var(--osd-accent)',
                  }}
                >
                  {s.cap}
                </div>
                <div
                  style={{
                    marginTop: 8,
                    fontFamily: font.body,
                    fontSize: 23,
                    color: palette.muted,
                  }}
                >
                  {s.note}
                </div>
              </div>
            </div>
          ))}
        </div>
        <div style={{ marginTop: 34 }}>
          <Rule />
          <div
            style={{
              marginTop: 16,
              fontFamily: font.mono,
              fontSize: 16,
              letterSpacing: '0.1em',
              color: palette.dim,
            }}
          >
            PRIMARY RESEARCH // SAVH — SINGAPORE ASSOCIATION OF THE VISUALLY HANDICAPPED, 2026
          </div>
        </div>
      </div>
    </div>
  );
};

// ─── Page 7 · The trade-off ──────────────────────────────────────────────────
const TradeOff: Page = () => {
  const col = (
    title: string,
    color: string,
    pros: string[],
    cons: string[],
  ) => (
    <div style={{ flex: 1, border: `1px solid ${palette.line}`, padding: '40px 44px' }}>
      <div
        style={{
          fontFamily: 'var(--osd-font-display)',
          fontSize: 62,
          color,
          lineHeight: 1,
        }}
      >
        {title}
      </div>
      <div style={{ marginTop: 30 }}>
        {pros.map((p) => (
          <div
            key={p}
            style={{
              display: 'flex',
              gap: 16,
              padding: '13px 0',
              fontSize: 25,
              lineHeight: 1.3,
            }}
          >
            <span style={{ color: 'var(--osd-accent)' }}>+</span>
            {p}
          </div>
        ))}
        {cons.map((c) => (
          <div
            key={c}
            style={{
              display: 'flex',
              gap: 16,
              padding: '13px 0',
              fontSize: 25,
              lineHeight: 1.3,
              color: palette.muted,
            }}
          >
            <span style={{ color: palette.dim }}>−</span>
            {c}
          </div>
        ))}
      </div>
    </div>
  );
  return (
    <div style={fill}>
      <Styles />
      <Chrome />
      <div
        style={{
          position: 'absolute',
          inset: 0,
          padding: '150px 100px 100px',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <Tag color="var(--osd-accent)">// STAGE 01 EMPATHIZE — WHAT WE OBSERVED</Tag>
        <h2
          style={{
            fontFamily: 'var(--osd-font-display)',
            fontSize: 92,
            lineHeight: 0.98,
            margin: '22px 0 44px',
          }}
        >
          THE DAILY TRADE-OFF
        </h2>
        <div style={{ display: 'flex', gap: 44, flex: 1 }}>
          {col('THE CANE', palette.text, ['Feels the ground — trusted, always ready', 'Leaves hands and hearing free'], [
            'Cannot feel overhead signs or barriers',
            'Cannot read bus numbers or give directions',
          ])}
          {col('THE PHONE', 'var(--osd-accent)', ['Maps, bus arrivals, information'], [
            'Stops you mid-pavement to check',
            'Occupies the hands and attention you need for safety',
          ])}
        </div>
        <div
          style={{
            marginTop: 44,
            background: 'var(--osd-accent)',
            color: palette.bg,
            padding: '26px 40px',
            display: 'flex',
            alignItems: 'center',
            gap: 30,
          }}
        >
          <span
            style={{
              fontFamily: 'var(--osd-font-display)',
              fontSize: 40,
              whiteSpace: 'nowrap',
            }}
          >
            STOP-AND-CHECK
          </span>
          <span style={{ fontSize: 26, lineHeight: 1.3 }}>
            every route decision costs half a minute of stillness — a pause in the middle of
            a footpath. safety or knowledge: never both.
          </span>
        </div>
      </div>
    </div>
  );
};

// ─── Page 8 · Divider: Define ────────────────────────────────────────────────
const DividerDefine: Page = () => (
  <StageDivider
    stageIndex={1}
    question="After three sessions with SAVH, one problem kept surfacing. We made it ours."
  />
);

// ─── Page 9 · Problem statement ──────────────────────────────────────────────
const ProblemStatement: Page = () => (
  <div style={fill}>
    <Styles />
    <Chrome />
    <Halftone
      style={{
        right: 100,
        bottom: 110,
        width: 320,
        height: 110,
        maskImage: 'linear-gradient(100deg, black 20%, transparent 95%)',
        WebkitMaskImage: 'linear-gradient(100deg, black 20%, transparent 95%)',
      }}
    />
    <div
      style={{
        position: 'absolute',
        inset: 0,
        padding: '170px 100px 110px',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
      }}
    >
      <Tag color="var(--osd-accent)">// STAGE 02 DEFINE — OUR PROBLEM STATEMENT</Tag>
      <h2
        style={{
          fontFamily: 'var(--osd-font-display)',
          fontSize: 84,
          lineHeight: 1.06,
          margin: '40px 0 0',
          maxWidth: 1620,
        }}
      >
        HOW MIGHT A VISUALLY IMPAIRED PERSON TRAVEL INDEPENDENTLY —{' '}
        <span style={{ color: 'var(--osd-accent)' }}>WITHOUT PUTTING DOWN THE CANE,</span>{' '}
        WITHOUT STOPPING TO CHECK A PHONE, AND WITHOUT WAITING FOR SOMEONE TO HELP?
      </h2>
      <p
        style={{
          margin: '48px 0 0',
          fontSize: 30,
          lineHeight: 1.45,
          color: palette.muted,
          maxWidth: 1100,
        }}
      >
        our yardstick, agreed with users: if a solution costs hands, attention or dignity —
        it fails the user-first test.
      </p>
    </div>
  </div>
);

// ─── Page 10 · Divider: Market research ──────────────────────────────────────
const DividerResearch: Page = () => (
  <StageDivider
    stageIndex={2}
    question="What already exists — and why isn't it enough for the person holding a cane?"
  />
);

// ─── Page 11 · Alternatives table ────────────────────────────────────────────
const Alternatives: Page = () => {
  const rows = [
    {
      name: 'BE MY EYES',
      img: bemyEyesImg,
      what: 'free app connecting users to sighted volunteers over video call',
      pros: 'free · human judgement · handles almost any task',
      cons: 'needs a phone in hand · depends on volunteer availability · not built for continuous navigation',
    },
    {
      name: 'ENVISION GLASSES',
      img: envisionImg,
      what: 'AI glasses (built on Google Glass) that read text and identify objects',
      pros: 'hands-free reading · recognises objects & people',
      cons: '≈ US$2,500 (S$3,259 list) · reading-first, not navigation-first · screen and camera up front all day',
    },
    {
      name: 'ORCAM MYEYE',
      img: orcamImg,
      what: 'discreet clip-on camera that reads text aloud',
      pros: 'small & discreet · strong text reading',
      cons: 'US$2,500–4,250 · reads text — it does not guide you anywhere',
    },
  ];
  return (
    <div style={fill}>
      <Styles />
      <Chrome />
      <div
        style={{
          position: 'absolute',
          inset: 0,
          padding: '150px 100px 100px',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <Tag color="var(--osd-accent)">// STAGE 03 MARKET RESEARCH — EXISTING SOLUTIONS</Tag>
        <h2
          style={{
            fontFamily: 'var(--osd-font-display)',
            fontSize: 92,
            lineHeight: 0.98,
            margin: '22px 0 40px',
          }}
        >
          GOOD TOOLS. <span style={{ color: 'var(--osd-accent)' }}>WRONG JOB.</span>
        </h2>
        <div style={{ display: 'flex', fontFamily: font.mono, fontSize: 17, letterSpacing: '0.1em', color: palette.muted, paddingBottom: 14 }}>
          <div style={{ width: 280 }}>PRODUCT</div>
          <div style={{ width: 200 }}>SNAPSHOT</div>
          <div style={{ width: 330 }}>WHAT IT IS</div>
          <div style={{ flex: 1 }}>PROS</div>
          <div style={{ flex: 1.1 }}>CONS — WHY IT MISSES</div>
        </div>
        <Rule />
        {rows.map((r) => (
          <div key={r.name}>
            <div style={{ display: 'flex', alignItems: 'stretch', padding: '26px 0', gap: 0 }}>
              <div style={{ width: 280, paddingRight: 20 }}>
                <span
                  style={{
                    fontFamily: 'var(--osd-font-display)',
                    fontSize: 33,
                    lineHeight: 1.05,
                    display: 'block',
                  }}
                >
                  {r.name}
                </span>
              </div>
              <div
                style={{
                  width: 200,
                  height: 110,
                  marginRight: 30,
                  border: `1px solid ${palette.line}`,
                  overflow: 'hidden',
                  display: 'grid',
                  placeItems: 'center',
                  flexShrink: 0,
                }}
              >
                <img
                  src={r.img}
                  alt={r.name}
                  style={{
                    width: '100%',
                    height: '100%',
                    objectFit: 'cover',
                    background: '#F4F4EC',
                  }}
                />
              </div>
              <div style={{ width: 330, paddingRight: 30, fontSize: 21, lineHeight: 1.35, color: palette.muted }}>
                {r.what}
              </div>
              <div style={{ flex: 1, paddingRight: 30, fontSize: 21, lineHeight: 1.35 }}>
                {r.pros}
              </div>
              <div style={{ flex: 1.1, fontSize: 21, lineHeight: 1.35, color: palette.muted }}>
                {r.cons}
              </div>
            </div>
            <Rule />
          </div>
        ))}
        <div
          style={{
            marginTop: 'auto',
            fontFamily: font.mono,
            fontSize: 16,
            letterSpacing: '0.1em',
            color: palette.dim,
          }}
        >
          SOURCES: OFFICIAL PRODUCT PAGES & PUBLISHED PRICING, 2026 // PROS AND CONS VERIFIED
          AGAINST USER FEEDBACK FROM SAVH SESSIONS
        </div>
      </div>
    </div>
  );
};

// ─── Page 12 · The gap ───────────────────────────────────────────────────────
const TheGap: Page = () => {
  const cards = [
    { n: '01', t: 'COST', d: 'US$2,500+ price tags put existing assistive glasses out of reach for most families.' },
    { n: '02', t: 'INDEPENDENCE', d: 'every alternative still needs a phone in hand, a volunteer on call — or simply stops at reading.' },
    { n: '03', t: 'DIGNITY', d: 'keeping dignity intact: no stopping, no staring at a screen, no needing a guide everywhere you go.' },
  ];
  return (
    <div style={fill}>
      <Styles />
      <Chrome />
      <Checker style={{ right: 100, top: 130 }} />
      <div
        style={{
          position: 'absolute',
          inset: 0,
          padding: '160px 100px 110px',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <Tag color="var(--osd-accent)">// STAGE 03 MARKET RESEARCH — THE GAP</Tag>
        <h2
          style={{
            fontFamily: 'var(--osd-font-display)',
            fontSize: 96,
            lineHeight: 0.97,
            margin: '24px 0 54px',
            maxWidth: 1500,
          }}
        >
          NOTHING WALKS YOU THERE.
        </h2>
        <div style={{ display: 'flex', gap: 36 }}>
          {cards.map((c) => (
            <div
              key={c.n}
              style={{
                flex: 1,
                border: `1px solid ${palette.line}`,
                borderTop: `6px solid var(--osd-accent)`,
                padding: '40px 40px 44px',
              }}
            >
              <div
                style={{
                  fontFamily: font.mono,
                  fontSize: 20,
                  color: 'var(--osd-accent)',
                  letterSpacing: '0.14em',
                }}
              >
                {c.n}
              </div>
              <div
                style={{
                  fontFamily: 'var(--osd-font-display)',
                  fontSize: 56,
                  marginTop: 16,
                }}
              >
                {c.t}
              </div>
              <p style={{ margin: '20px 0 0', fontSize: 25, lineHeight: 1.45, color: palette.muted }}>
                {c.d}
              </p>
            </div>
          ))}
        </div>
        <p
          style={{
            margin: '56px 0 0',
            fontSize: 32,
            lineHeight: 1.4,
            color: palette.text,
            maxWidth: 1300,
          }}
        >
          the gap is navigation: genuinely hands-free, genuinely affordable, built around
          the journey — not around reading.
        </p>
      </div>
    </div>
  );
};

// ─── Page 13 · Divider: Ideate ───────────────────────────────────────────────
const DividerIdeate: Page = () => (
  <StageDivider
    stageIndex={3}
    question="What should this device be — and, just as important, what should it never be?"
  />
);

// ─── Page 14 · Three design rules ────────────────────────────────────────────
const DesignRules: Page = () => {
  const rules = [
    {
      n: 'RULE 01',
      t: 'AUDIO-FIRST',
      d: 'one clear voice in the ear. eyes, hands and hearing stay exactly where they belong — on the world.',
    },
    {
      n: 'RULE 02',
      t: 'CANE-AWARE',
      d: 'the cane stays the ground sensor. we detect only what it cannot feel — head-height and beyond.',
    },
    {
      n: 'RULE 03',
      t: 'NAVIGATION-FIRST',
      d: 'directions, bus arrivals, arrival alerts — the whole journey end to end, not another reading gadget.',
    },
  ];
  return (
    <div style={fill}>
      <Styles />
      <Chrome />
      <div
        style={{
          position: 'absolute',
          inset: 0,
          padding: '160px 100px 110px',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <Tag color="var(--osd-accent)">// STAGE 04 IDEATE — THE DECISION</Tag>
        <h2
          style={{
            fontFamily: 'var(--osd-font-display)',
            fontSize: 90,
            lineHeight: 0.98,
            margin: '24px 0 56px',
            maxWidth: 1550,
          }}
        >
          NOT A SMARTER CANE — <span style={{ color: 'var(--osd-accent)' }}>A GUIDE FOR THE JOURNEY.</span>
        </h2>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          {rules.map((r, i) => (
            <div key={r.n}>
              <Rule />
              <div style={{ display: 'flex', gap: 50, alignItems: 'flex-start', padding: '34px 0' }}>
                <span
                  style={{
                    fontFamily: font.mono,
                    fontSize: 21,
                    letterSpacing: '0.14em',
                    color: 'var(--osd-accent)',
                    width: 150,
                    flexShrink: 0,
                    paddingTop: 10,
                  }}
                >
                  {r.n}
                </span>
                <span
                  style={{
                    fontFamily: 'var(--osd-font-display)',
                    fontSize: 62,
                    lineHeight: 1,
                    width: 480,
                    flexShrink: 0,
                  }}
                >
                  {r.t}
                </span>
                <span style={{ fontSize: 27, lineHeight: 1.4, color: palette.muted, paddingTop: 6 }}>
                  {r.d}
                </span>
              </div>
            </div>
          ))}
          <Rule />
        </div>
      </div>
    </div>
  );
};

// ─── Page 15 · Divider: Prototype ────────────────────────────────────────────
const DividerPrototype: Page = () => (
  <StageDivider
    stageIndex={4}
    question="Three iterations later, here is what we actually built — and the engineering underneath it."
  />
);

// ─── Page 16 · What it is ────────────────────────────────────────────────────
const WhatItIs: Page = () => {
  const jobs = [
    { t: 'GET THERE', d: 'spoken turn-by-turn directions and bus routes' },
    { t: "DON'T STOP", d: 'head-height hazards called out before you reach them' },
    { t: 'RIDE THE BUS', d: 'live arrival times and a wake-me-up at your stop' },
  ];
  return (
    <div style={fill}>
      <Styles />
      <Chrome />
      <div
        style={{
          position: 'absolute',
          inset: 0,
          padding: '150px 100px 100px',
          display: 'flex',
          gap: 70,
        }}
      >
        <div style={{ width: 760, flexShrink: 0, display: 'flex', flexDirection: 'column' }}>
          <Tag color="var(--osd-accent)">// STAGE 05 PROTOTYPE — WHAT IT IS</Tag>
          <h2
            style={{
              fontFamily: 'var(--osd-font-display)',
              fontSize: 84,
              lineHeight: 0.98,
              margin: '24px 0 36px',
            }}
          >
            GLASSES THAT TALK YOU THROUGH THE JOURNEY
          </h2>
          <p style={{ margin: 0, fontSize: 27, lineHeight: 1.5, color: palette.muted }}>
            open-ear audio — you hear Cortex <em>and</em> the traffic. a dual camera watches
            ahead; a Raspberry Pi 5 with an AI accelerator does the thinking. your phone
            stays in your pocket.
          </p>
          <div style={{ marginTop: 44 }}>
            {jobs.map((j, i) => (
              <div key={j.t}>
                <Rule />
                <div style={{ display: 'flex', gap: 34, padding: '22px 0', alignItems: 'baseline' }}>
                  <span
                    style={{
                      fontFamily: font.mono,
                      fontSize: 18,
                      color: 'var(--osd-accent)',
                      letterSpacing: '0.1em',
                      width: 40,
                    }}
                  >
                    {String(i + 1).padStart(2, '0')}
                  </span>
                  <span
                    style={{
                      fontFamily: 'var(--osd-font-display)',
                      fontSize: 40,
                      width: 250,
                      flexShrink: 0,
                    }}
                  >
                    {j.t}
                  </span>
                  <span style={{ fontSize: 24, color: palette.muted, lineHeight: 1.35 }}>{j.d}</span>
                </div>
              </div>
            ))}
            <Rule />
          </div>
        </div>
        <div
          style={{
            flex: 1,
            position: 'relative',
            border: `1px solid ${palette.line}`,
            overflow: 'hidden',
            background: `radial-gradient(ellipse at 50% 30%, #1B1B10 0%, ${palette.bg} 70%)`,
          }}
        >
          <Rings
            size={480}
            style={{ left: '50%', top: '6%', transform: 'translateX(-50%)' }}
          />
          {/* static noise bars */}
          <div style={{ position: 'absolute', inset: 0, opacity: 0.5 }}>
            {[
              { top: '9%', left: '8%', w: 90 },
              { top: '14%', left: '64%', w: 130 },
              { top: '22%', left: '18%', w: 60 },
              { top: '30%', left: '74%', w: 90 },
              { top: '52%', left: '6%', w: 110 },
              { top: '64%', left: '80%', w: 70 },
              { top: '76%', left: '12%', w: 90 },
            ].map((b, bi) => (
              <div
                key={bi}
                style={{
                  position: 'absolute',
                  top: b.top,
                  left: b.left,
                  width: b.w,
                  height: 3,
                  background: bi % 2 === 0 ? 'var(--osd-accent)' : palette.line,
                  opacity: bi % 2 === 0 ? 0.55 : 0.8,
                }}
              />
            ))}
          </div>
          <Halftone
            style={{
              right: 30,
              top: 30,
              width: 190,
              height: 80,
              maskImage: 'linear-gradient(100deg, black 20%, transparent 95%)',
              WebkitMaskImage: 'linear-gradient(100deg, black 20%, transparent 95%)',
            }}
          />
          <img
            src={irfanV3}
            alt="Irfan wearing Cortex V3 prototype"
            style={{
              position: 'absolute',
              inset: 0,
              width: '100%',
              height: '100%',
              objectFit: 'contain',
              objectPosition: 'center bottom',
              filter: 'drop-shadow(0 30px 60px rgba(0,0,0,0.6))',
            }}
          />
          <div
            style={{
              position: 'absolute',
              left: 0,
              bottom: 0,
              right: 0,
              background: 'rgba(10,10,8,0.82)',
              padding: '16px 24px',
              fontFamily: font.mono,
              fontSize: 17,
              letterSpacing: '0.12em',
              color: 'var(--osd-accent)',
            }}
          >
            PROTOTYPE V3 // OPEN-EAR AUDIO · DUAL CAMERA · PI 5 + NPU
          </div>
        </div>
      </div>
    </div>
  );
};

// ─── Page 17 · Five specialists ──────────────────────────────────────────────
const FiveSpecialists: Page = () => {
  const layers = [
    { n: 'L0', t: 'GUARDIAN', d: 'spots hazards and warns in under 100 ms — before cloud could even wake up' },
    { n: 'L1', t: 'LEARNER', d: 'recognises places and things, from the bus stop to the kopitiam' },
    { n: 'L2', t: 'THINKER', d: 'a conversational AI brain you can just ask' },
    { n: 'L3', t: 'GUIDE', d: 'directions, bus arrivals and the route state machine' },
    { n: 'L4', t: 'MEMORY', d: 'remembers your frequently visited locations' },
  ];
  return (
    <div style={fill}>
      <Styles />
      <Chrome />
      <div
        style={{
          position: 'absolute',
          inset: 0,
          padding: '150px 100px 100px',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <Tag color="var(--osd-accent)">// STAGE 05 PROTOTYPE — HOW IT THINKS</Tag>
        <h2
          style={{
            fontFamily: 'var(--osd-font-display)',
            fontSize: 92,
            lineHeight: 0.98,
            margin: '22px 0 20px',
          }}
        >
          FIVE SPECIALISTS, ONE VOICE
        </h2>
        <p style={{ margin: 0, fontSize: 26, color: palette.muted, maxWidth: 1100 }}>
          Cortex runs five cooperating layers — four on the glasses, one in the cloud.
        </p>
        <div style={{ display: 'flex', gap: 24, marginTop: 50, flex: 1, minHeight: 0 }}>
          {layers.map((l, i) => (
            <div
              key={l.n}
              style={{
                flex: 1,
                border: `1px solid ${palette.line}`,
                borderTop: i === 0 ? `6px solid var(--osd-accent)` : `1px solid ${palette.line}`,
                padding: '34px 28px',
                display: 'flex',
                flexDirection: 'column',
              }}
            >
              <div
                style={{
                  fontFamily: 'var(--osd-font-display)',
                  fontSize: 64,
                  color: i === 0 ? 'var(--osd-accent)' : palette.text,
                  lineHeight: 1,
                }}
              >
                {l.n}
              </div>
              <div
                style={{
                  fontFamily: font.mono,
                  fontSize: 19,
                  letterSpacing: '0.12em',
                  marginTop: 18,
                }}
              >
                {l.t}
              </div>
              <p
                style={{
                  margin: '16px 0 0',
                  fontSize: 21,
                  lineHeight: 1.4,
                  color: palette.muted,
                }}
              >
                {l.d}
              </p>
            </div>
          ))}
        </div>
        <div
          style={{
            marginTop: 40,
            background: 'var(--osd-accent)',
            color: palette.bg,
            padding: '20px 36px',
            fontFamily: 'var(--osd-font-display)',
            fontSize: 34,
          }}
        >
          ONE RULE: SAFETY NEVER LEAVES THE DEVICE.
        </div>
      </div>
    </div>
  );
};

// ─── Page 18 · Architecture: hybrid edge-cloud ───────────────────────────────
const ArchHybrid: Page = () => {
  const local = ['YOLO vision (runs offline on the NPU)', 'depth sensing + ToF laser', 'safety fusion & alert engine', 'navigation state machine', 'offline route following'];
  const cloud = ['Gemini Live — the conversational brain', 'Google Maps routing', 'LTA bus arrival times', 'memory sync to the cloud'];
  const panel = (title: string, badge: string, items: string[], accent: boolean) => (
    <div
      style={{
        flex: 1,
        border: `1px solid ${accent ? 'var(--osd-accent)' : palette.line}`,
        padding: '38px 42px',
        background: accent ? 'rgba(216,229,22,0.05)' : 'transparent',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <span
          style={{
            fontFamily: 'var(--osd-font-display)',
            fontSize: 46,
            color: accent ? 'var(--osd-accent)' : palette.text,
          }}
        >
          {title}
        </span>
        <span
          style={{
            fontFamily: font.mono,
            fontSize: 18,
            letterSpacing: '0.12em',
            color: accent ? 'var(--osd-accent)' : palette.muted,
          }}
        >
          {badge}
        </span>
      </div>
      <div style={{ marginTop: 26 }}>
        {items.map((it) => (
          <div
            key={it}
            style={{
              display: 'flex',
              gap: 16,
              padding: '12px 0',
              fontSize: 24,
              lineHeight: 1.35,
              color: accent ? palette.text : palette.muted,
            }}
          >
            <span style={{ fontFamily: font.mono, color: accent ? 'var(--osd-accent)' : palette.dim }}>
              //
            </span>
            {it}
          </div>
        ))}
      </div>
    </div>
  );
  return (
    <div style={fill}>
      <Styles />
      <Chrome />
      <div
        style={{
          position: 'absolute',
          inset: 0,
          padding: '150px 100px 100px',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <Tag color="var(--osd-accent)">// TECHNICAL ARCHITECTURE 1 OF 3</Tag>
        <h2
          style={{
            fontFamily: 'var(--osd-font-display)',
            fontSize: 84,
            lineHeight: 0.98,
            margin: '22px 0 44px',
            maxWidth: 1550,
          }}
        >
          FAST REFLEXES LOCAL, <span style={{ color: 'var(--osd-accent)' }}>BIG BRAINS ON CALL</span>
        </h2>
        <div style={{ display: 'flex', gap: 0, alignItems: 'stretch' }}>
          {panel('ON-DEVICE', 'REACTS < 100 MS', local, true)}
          <div
            style={{
              width: 120,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 12,
              fontFamily: font.mono,
              fontSize: 17,
              color: palette.muted,
              letterSpacing: '0.1em',
            }}
          >
            <div style={{ width: 2, flex: 1, background: palette.line }} />
            <span>⇄</span>
            <span style={{ textAlign: 'center', lineHeight: 1.5 }}>
              ONLY WHAT
              <br />
              HELPS
            </span>
            <div style={{ width: 2, flex: 1, background: palette.line }} />
          </div>
          {panel('ON-DEMAND', 'CLOUD', cloud, false)}
        </div>
        <div style={{ display: 'flex', gap: 36, marginTop: 40, alignItems: 'stretch' }}>
          <div
            style={{
              border: `2px dashed ${palette.line}`,
              padding: '22px 34px',
              fontSize: 24,
              lineHeight: 1.4,
              color: palette.muted,
              flex: 1.4,
            }}
          >
            <span style={{ fontFamily: font.mono, color: 'var(--osd-accent)', letterSpacing: '0.1em' }}>
              CONNECTIVITY MONITOR —{' '}
            </span>
            walking into an MRT underpass with no signal? safety alerts and route-following
            keep running on-device. the journey does not stop when the network does.
          </div>
          <div
            style={{
              flex: 1,
              position: 'relative',
              border: `1px solid ${palette.line}`,
              overflow: 'hidden',
              minHeight: 230,
            }}
          >
            <img
              src={standaloneImg}
              alt="Cortex standalone compute unit and sensor glasses"
              style={{ width: '100%', height: '100%', objectFit: 'cover', position: 'absolute', inset: 0 }}
            />
            <div
              style={{
                position: 'absolute',
                left: 0,
                bottom: 0,
                right: 0,
                background: 'rgba(10,10,8,0.82)',
                padding: '10px 18px',
                fontFamily: font.mono,
                fontSize: 15,
                letterSpacing: '0.12em',
                color: 'var(--osd-accent)',
              }}
            >
              THE STANDALONE UNIT // PI 5 + NPU + DUAL CAMERAS
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

// ─── Page 19 · Architecture: the voice loop ──────────────────────────────────
const ArchVoice: Page = () => {
  const steps = [
    { t: 'EARS', d: 'bluetooth mic + voice activity detection' },
    { t: 'UNDERSTAND', d: 'speech-to-text + the Gemini Live brain' },
    { t: 'DECIDE', d: 'intent router — 97.7% accuracy on 14 intents' },
    { t: 'ACT', d: 'tool calls: navigate, bus times, find places' },
    { t: 'SPEAK', d: 'a natural voice answers in your ear' },
  ];
  return (
    <div style={fill}>
      <Styles />
      <Chrome />
      <div
        style={{
          position: 'absolute',
          inset: 0,
          padding: '150px 100px 100px',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <Tag color="var(--osd-accent)">// TECHNICAL ARCHITECTURE 2 OF 3</Tag>
        <h2
          style={{
            fontFamily: 'var(--osd-font-display)',
            fontSize: 88,
            lineHeight: 0.98,
            margin: '22px 0 16px',
          }}
        >
          ONE VOICE IN. ONE VOICE OUT.
        </h2>
        <p style={{ margin: 0, fontSize: 26, color: palette.muted, maxWidth: 1200 }}>
          no buttons to find, no screen to unlock — talk like you would to a friend.
        </p>
        <div style={{ display: 'flex', alignItems: 'stretch', gap: 0, marginTop: 70 }}>
          {steps.map((s, i) => (
            <div key={s.t} style={{ display: 'flex', flex: 1, alignItems: 'stretch' }}>
              <div
                style={{
                  flex: 1,
                  border: `1px solid ${i === 2 ? 'var(--osd-accent)' : palette.line}`,
                  padding: '30px 26px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 14,
                }}
              >
                <span
                  style={{
                    fontFamily: font.mono,
                    fontSize: 17,
                    color: palette.dim,
                    letterSpacing: '0.12em',
                  }}
                >
                  {String(i + 1).padStart(2, '0')}
                </span>
                <span
                  style={{
                    fontFamily: 'var(--osd-font-display)',
                    fontSize: 40,
                    color: i === 2 ? 'var(--osd-accent)' : palette.text,
                    lineHeight: 1,
                  }}
                >
                  {s.t}
                </span>
                <span style={{ fontSize: 20, lineHeight: 1.4, color: palette.muted }}>{s.d}</span>
              </div>
              {i < steps.length - 1 && (
                <div
                  style={{
                    width: 44,
                    display: 'grid',
                    placeItems: 'center',
                    color: 'var(--osd-accent)',
                    fontFamily: font.mono,
                    fontSize: 26,
                  }}
                >
                  →
                </div>
              )}
            </div>
          ))}
        </div>
        <div
          style={{
            marginTop: 54,
            display: 'flex',
            alignItems: 'center',
            gap: 24,
            fontFamily: font.mono,
            fontSize: 19,
            letterSpacing: '0.12em',
            color: palette.muted,
          }}
        >
          <span style={{ color: 'var(--osd-accent)', fontSize: 26 }}>⟲</span>
          CONTINUOUS CONVERSATION — INTERRUPT ANYTIME, LIKE A HUMAN COMPANION
        </div>
        <div style={{ marginTop: 'auto' }}>
          <Rule />
          <div
            style={{
              marginTop: 16,
              fontFamily: font.mono,
              fontSize: 16,
              letterSpacing: '0.1em',
              color: palette.dim,
            }}
          >
            FALLBACK CHAIN: CARTESIA VOICE → LOCAL ENGINE — THE VOICE NEVER DIES MID-JOURNEY
          </div>
        </div>
      </div>
    </div>
  );
};

// ─── Page 20 · Architecture: journey state machine ───────────────────────────
const ArchStates: Page = () => {
  const states = ['INACTIVE', 'LOADING ROUTE', 'NAVIGATING', 'WAITING FOR BUS', 'ON VEHICLE', 'ARRIVED'];
  const modes = [
    { t: 'OUTDOOR', d: 'full hazard watch' },
    { t: 'INDOOR', d: 'cane-aware mode' },
    { t: 'BUS STOP', d: 'bus-number vision' },
    { t: 'TRANSIT', d: 'stops & interchanges' },
    { t: 'IDLE', d: 'conversation only' },
  ];
  return (
    <div style={fill}>
      <Styles />
      <Chrome />
      <div
        style={{
          position: 'absolute',
          inset: 0,
          padding: '150px 100px 100px',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <Tag color="var(--osd-accent)">// TECHNICAL ARCHITECTURE 3 OF 3</Tag>
        <h2
          style={{
            fontFamily: 'var(--osd-font-display)',
            fontSize: 88,
            lineHeight: 0.98,
            margin: '22px 0 20px',
          }}
        >
          IT KNOWS WHERE YOU ARE IN THE JOURNEY
        </h2>
        <p style={{ margin: 0, fontSize: 26, color: palette.muted, maxWidth: 1250 }}>
          a navigation engine moves through six states — so the right help arrives at the
          right moment, without being asked.
        </p>
        <div style={{ display: 'flex', gap: 14, marginTop: 66 }}>
          {states.map((s, i) => (
            <div key={s} style={{ display: 'flex', flex: 1, alignItems: 'center' }}>
              <div
                style={{
                  flex: 1,
                  textAlign: 'center',
                  padding: '26px 8px',
                  border: `2px solid ${i === 2 || i === 3 ? 'var(--osd-accent)' : palette.line}`,
                  background: i === 2 || i === 3 ? 'rgba(216,229,22,0.07)' : 'transparent',
                  fontFamily: font.mono,
                  fontSize: 19,
                  letterSpacing: '0.06em',
                  lineHeight: 1.3,
                  color: i === 2 || i === 3 ? 'var(--osd-accent)' : palette.text,
                }}
              >
                {s}
              </div>
              {i < states.length - 1 && (
                <span
                  style={{
                    color: 'var(--osd-accent)',
                    fontFamily: font.mono,
                    fontSize: 22,
                    padding: '0 4px',
                  }}
                >
                  →
                </span>
              )}
            </div>
          ))}
        </div>
        <Tag style={{ marginTop: 76 }}>FIVE MODES THAT SWITCH AUTOMATICALLY</Tag>
        <div style={{ display: 'flex', gap: 14, marginTop: 22 }}>
          {modes.map((m) => (
            <div
              key={m.t}
              style={{
                flex: 1,
                border: `1px solid ${palette.line}`,
                borderTop: `5px solid ${palette.line}`,
                padding: '22px 24px',
              }}
            >
              <div style={{ fontFamily: 'var(--osd-font-display)', fontSize: 34 }}>{m.t}</div>
              <div style={{ marginTop: 8, fontSize: 20, color: palette.muted }}>{m.d}</div>
            </div>
          ))}
        </div>
        <div
          style={{
            marginTop: 'auto',
            fontFamily: font.mono,
            fontSize: 16,
            letterSpacing: '0.1em',
            color: palette.dim,
          }}
        >
          GPS, CAMERA AND CONTEXT DECIDE THE MODE — THE USER NEVER TOUCHES A SETTING
        </div>
      </div>
    </div>
  );
};

// ─── Page 21 · Cane-aware safety matrix ──────────────────────────────────────
const CaneMatrix: Page = () => {
  const rows = [
    { h: 'GROUND-LEVEL OBSTACLES', cane: 'DETECTED', cortex: 'STAYS QUIET', why: 'the cane already owns the ground' },
    { h: 'OVERHEAD BARRIERS & BRANCHES', cane: 'MISSED', cortex: 'ALERT < 100 MS', why: 'the classic head-height blind spot' },
    { h: 'STAIRS GOING UP', cane: 'TOO LATE', cortex: 'ALERT < 100 MS', why: 'spotted before the first step' },
    { h: 'FAST-APPROACHING VEHICLES', cane: 'MISSED', cortex: 'ALERT + HAPTIC', why: 'speed measured, not guessed' },
  ];
  const cellColor = (v: string) =>
    v.startsWith('ALERT') || v === 'STAYS QUIET' ? 'var(--osd-accent)' : palette.muted;
  return (
    <div style={fill}>
      <Styles />
      <Chrome />
      <div
        style={{
          position: 'absolute',
          inset: 0,
          padding: '150px 100px 100px',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <Tag color="var(--osd-accent)">// PROTOTYPE — CANE-AWARE BY DESIGN</Tag>
        <h2
          style={{
            fontFamily: 'var(--osd-font-display)',
            fontSize: 88,
            lineHeight: 0.98,
            margin: '22px 0 44px',
          }}
        >
          THE CANE STAYS THE CANE. <span style={{ color: 'var(--osd-accent)' }}>AI FILLS THE BLIND SPOTS.</span>
        </h2>
        <div style={{ display: 'flex', fontFamily: font.mono, fontSize: 17, letterSpacing: '0.1em', color: palette.muted, paddingBottom: 14 }}>
          <div style={{ width: 470 }}>HAZARD</div>
          <div style={{ width: 300 }}>WHITE CANE</div>
          <div style={{ width: 340 }}>CORTEX</div>
          <div style={{ flex: 1 }}>WHY</div>
        </div>
        <Rule />
        {rows.map((r) => (
          <div key={r.h}>
            <div style={{ display: 'flex', alignItems: 'center', padding: '27px 0' }}>
              <div style={{ width: 470, fontFamily: font.body, fontWeight: 700, fontSize: 26, letterSpacing: '0.01em' }}>
                {r.h}
              </div>
              <div style={{ width: 300, fontFamily: font.mono, fontSize: 20, color: palette.muted }}>
                {r.cane}
              </div>
              <div style={{ width: 340, fontFamily: font.mono, fontSize: 20, color: cellColor(r.cortex) }}>
                {r.cortex}
              </div>
              <div style={{ flex: 1, fontSize: 22, color: palette.muted }}>{r.why}</div>
            </div>
            <Rule />
          </div>
        ))}
        <p
          style={{
            marginTop: 44,
            fontSize: 27,
            lineHeight: 1.45,
            color: palette.text,
            maxWidth: 1400,
          }}
        >
          indoors, Cortex stays quiet about walls and curbs the cane already handles —{' '}
          <span style={{ color: 'var(--osd-accent)' }}>
            less noise, more trust.
          </span>{' '}
          that single decision came straight from user testing.
        </p>
      </div>
    </div>
  );
};

// ─── Page 22 · Divider: Test ─────────────────────────────────────────────────
const DividerTest: Page = () => (
  <StageDivider
    stageIndex={5}
    question="Does it work for real users — and what did we get wrong the first time?"
  />
);

// ─── Page 23 · The pivot (V1 failure) ────────────────────────────────────────
const ThePivot: Page = () => (
  <div style={fill}>
    <Styles />
    <Chrome />
    <Rings size={640} style={{ right: -220, bottom: -280 }} />
    <div
      style={{
        position: 'absolute',
        inset: 0,
        padding: '170px 100px 110px',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
      }}
    >
      <Tag color="var(--osd-accent)">// STAGE 06 TEST — THE MOMENT WE LISTENED</Tag>
      <div
        style={{
          fontFamily: 'var(--osd-font-display)',
          fontSize: 190,
          lineHeight: 0.9,
          color: 'var(--osd-accent)',
          marginTop: 40,
        }}
      >
        “
      </div>
      <h2
        style={{
          fontFamily: 'var(--osd-font-display)',
          fontSize: 82,
          lineHeight: 1.08,
          margin: '0 0 0',
          maxWidth: 1560,
          fontWeight: 400,
        }}
      >
        THE SPATIAL AUDIO WAS OVERWHELMING —{' '}
        <span style={{ color: 'var(--osd-accent)' }}>
          WE COULDN'T HEAR OUR SURROUNDINGS.
        </span>
      </h2>
      <div
        style={{
          marginTop: 36,
          fontFamily: font.mono,
          fontSize: 20,
          letterSpacing: '0.14em',
          color: palette.muted,
        }}
      >
        — SAVH USER, AFTER TESTING PROTOTYPE V1
      </div>
      <p
        style={{
          margin: '52px 0 0',
          fontSize: 30,
          lineHeight: 1.5,
          color: palette.muted,
          maxWidth: 1300,
        }}
      >
        our first version poured 3D sound effects over everything. the test said:{' '}
        <span style={{ color: palette.text }}>
          for a blind user, your ears are a safety system — never drown them.
        </span>{' '}
        we stripped it back to one clear voice and rebuilt around the cane. failing here is
        what made V2 work.
      </p>
    </div>
  </div>
);

// ─── Page 24 · Iteration rounds ──────────────────────────────────────────────
const Iterations: Page = () => {
  const rounds = [
    {
      v: 'V1',
      t: 'FIRST BUILD',
      changes: ['spatial 3D audio everywhere', 'single camera, monocular depth', 'alerts for every obstacle'],
      verdict: 'FAILED THE TEST — too noisy, too distracting',
    },
    {
      v: 'V2',
      t: 'REBUILT AROUND THE CANE',
      changes: ['one clear voice, cane-aware alerts', 'dual camera + ToF laser depth', 'navigation made the core feature'],
      verdict: 'TESTED WITH SAVH — "finally, something we can live with"',
    },
    {
      v: 'V3',
      t: 'FIELD-READY',
      changes: ['outdoor & indoor auto-switching', 'live bus navigation end to end', 'lighter, wearable, open-ear'],
      verdict: 'VALIDATED — three sessions and counting',
    },
  ];
  return (
    <div style={fill}>
      <Styles />
      <Chrome />
      <div
        style={{
          position: 'absolute',
          inset: 0,
          padding: '150px 100px 100px',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <Tag color="var(--osd-accent)">// STAGE 06 TEST → ITERATE → REPEAT</Tag>
        <h2
          style={{
            fontFamily: 'var(--osd-font-display)',
            fontSize: 92,
            lineHeight: 0.98,
            margin: '22px 0 56px',
          }}
        >
          THREE ROUNDS OF LISTENING
        </h2>
        <div style={{ display: 'flex', alignItems: 'stretch', gap: 0 }}>
          {rounds.map((r, i) => (
            <div key={r.v} style={{ display: 'flex', flex: 1, alignItems: 'stretch' }}>
              <div
                style={{
                  flex: 1,
                  border: `1px solid ${i === 2 ? 'var(--osd-accent)' : palette.line}`,
                  padding: '36px 34px',
                  display: 'flex',
                  flexDirection: 'column',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 18 }}>
                  <span
                    style={{
                      fontFamily: 'var(--osd-font-display)',
                      fontSize: 72,
                      color: i === 2 ? 'var(--osd-accent)' : palette.text,
                      lineHeight: 1,
                    }}
                  >
                    {r.v}
                  </span>
                  <span
                    style={{
                      fontFamily: font.mono,
                      fontSize: 17,
                      letterSpacing: '0.12em',
                      color: palette.muted,
                    }}
                  >
                    {r.t}
                  </span>
                </div>
                <div style={{ marginTop: 26, display: 'flex', flexDirection: 'column', gap: 12 }}>
                  {r.changes.map((c) => (
                    <div key={c} style={{ display: 'flex', gap: 14, fontSize: 22, lineHeight: 1.35, color: palette.muted }}>
                      <span style={{ color: 'var(--osd-accent)' }}>+</span>
                      {c}
                    </div>
                  ))}
                </div>
                <div
                  style={{
                    marginTop: 'auto',
                    paddingTop: 24,
                    fontFamily: font.mono,
                    fontSize: 17,
                    letterSpacing: '0.04em',
                    lineHeight: 1.5,
                    color: i === 0 ? palette.dim : i === 2 ? 'var(--osd-accent)' : palette.text,
                  }}
                >
                  {r.verdict}
                </div>
              </div>
              {i < rounds.length - 1 && (
                <div
                  style={{
                    width: 64,
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: 8,
                    fontFamily: font.mono,
                    fontSize: 15,
                    letterSpacing: '0.1em',
                    color: 'var(--osd-accent)',
                  }}
                >
                  <span style={{ fontSize: 26 }}>→</span>
                  <span style={{ writingMode: 'vertical-rl' }}>ITERATE</span>
                </div>
              )}
            </div>
          ))}
        </div>
        <p
          style={{
            marginTop: 52,
            fontSize: 27,
            lineHeight: 1.45,
            color: palette.muted,
            maxWidth: 1350,
          }}
        >
          each loop back through design thinking made the product simpler, quieter and more
          trusted — the opposite of what we assumed on day one.
        </p>
      </div>
    </div>
  );
};

// ─── Page 25 · Proof ─────────────────────────────────────────────────────────
const Proof: Page = () => {
  const stats = [
    { n: 'US$186', l: 'parts cost — about 1/10 of existing AI glasses (US$2,500+)' },
    { n: '<100 MS', l: 'local hazard reaction — faster than a blink, no network needed' },
    { n: '97.7%', l: 'intent-routing accuracy across 14 spoken commands' },
    { n: '3', l: 'documented SAVH user sessions shaped every major decision' },
  ];
  return (
    <div style={fill}>
      <Styles />
      <Chrome />
      <Halftone
        style={{
          right: 100,
          top: 150,
          width: 300,
          height: 100,
          maskImage: 'linear-gradient(100deg, black 20%, transparent 95%)',
          WebkitMaskImage: 'linear-gradient(100deg, black 20%, transparent 95%)',
        }}
      />
      <div
        style={{
          position: 'absolute',
          inset: 0,
          padding: '160px 100px 110px',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <Tag color="var(--osd-accent)">// REFLECTION — WHAT THE NUMBERS SAY</Tag>
        <h2
          style={{
            fontFamily: 'var(--osd-font-display)',
            fontSize: 92,
            lineHeight: 0.98,
            margin: '24px 0 60px',
            maxWidth: 1500,
          }}
        >
          1/10 THE PRICE. <span style={{ color: 'var(--osd-accent)' }}>PROVEN WITH REAL USERS.</span>
        </h2>
        <div style={{ display: 'flex', flexWrap: 'wrap' }}>
          {stats.map((s, i) => (
            <div
              key={s.n}
              style={{
                width: '50%',
                borderTop: `1px solid ${palette.line}`,
                borderRight: i % 2 === 0 ? `1px solid ${palette.line}` : 'none',
                padding: '38px 60px 38px 0',
                paddingLeft: i % 2 === 1 ? 60 : 0,
              }}
            >
              <div
                style={{
                  fontFamily: 'var(--osd-font-display)',
                  fontSize: 110,
                  lineHeight: 0.95,
                  color: i === 0 ? 'var(--osd-accent)' : palette.text,
                }}
              >
                {s.n}
              </div>
              <div
                style={{
                  marginTop: 16,
                  fontSize: 24,
                  lineHeight: 1.4,
                  color: palette.muted,
                  maxWidth: 620,
                }}
              >
                {s.l}
              </div>
            </div>
          ))}
          <div style={{ width: '100%', borderTop: `1px solid ${palette.line}` }} />
        </div>
        <div
          style={{
            marginTop: 'auto',
            fontFamily: font.mono,
            fontSize: 16,
            letterSpacing: '0.1em',
            color: palette.dim,
          }}
        >
          COST COMPARISON: PUBLISHED PRICING OF ENVISION GLASSES / ORCAM MYEYE, 2026 // INTENT
          ACCURACY: INTERNAL TEST SET, 14 INTENTS
        </div>
      </div>
    </div>
  );
};

// ─── Page 26 · Acknowledgment ────────────────────────────────────────────────
const Acknowledgment: Page = () => {
  const next = [
    'a custom single-board computer — smaller, lighter, cooler',
    'longer battery life for a full school day',
    'fully local navigation, no cloud needed',
    'more testing with more SAVH users',
  ];
  return (
    <div style={fill}>
      <Styles />
      <Chrome />
      <Checker style={{ right: 100, bottom: 130 }} />
      <div
        style={{
          position: 'absolute',
          inset: 0,
          padding: '160px 100px 110px',
          display: 'flex',
          gap: 90,
        }}
      >
        <div style={{ width: 900, flexShrink: 0 }}>
          <Tag color="var(--osd-accent)">// ROOMS FOR IMPROVEMENT</Tag>
          <h2
            style={{
              fontFamily: 'var(--osd-font-display)',
              fontSize: 110,
              lineHeight: 0.96,
              margin: '26px 0 40px',
            }}
          >
            THIS IS A
            <br />
            PROTOTYPE.
          </h2>
          <p style={{ margin: 0, fontSize: 30, lineHeight: 1.55, color: palette.muted, maxWidth: 820 }}>
            Cortex is a working prototype — not a finished product. it took student tools,
            student budgets and student hours.{' '}
            <span style={{ color: palette.text }}>
              with the right resources, partners and time, Cortex gets better.
            </span>
          </p>
        </div>
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
          <Tag>THE ROADMAP</Tag>
          <div style={{ marginTop: 24 }}>
            {next.map((n, i) => (
              <div key={n}>
                <Rule />
                <div style={{ display: 'flex', gap: 28, padding: '24px 0', alignItems: 'baseline' }}>
                  <span style={{ fontFamily: font.mono, fontSize: 19, color: 'var(--osd-accent)' }}>
                    {String(i + 1).padStart(2, '0')}
                  </span>
                  <span style={{ fontSize: 26, lineHeight: 1.35 }}>{n}</span>
                </div>
              </div>
            ))}
            <Rule />
          </div>
          <div
            style={{
              marginTop: 40,
              display: 'flex',
              gap: 16,
              fontFamily: font.mono,
              fontSize: 17,
              letterSpacing: '0.1em',
              color: palette.muted,
            }}
          >
            <span style={{ border: `1px solid ${palette.line}`, padding: '10px 18px' }}>
              IVP SUBMISSION // 25 SEP
            </span>
            <span style={{ border: `1px solid var(--osd-accent)`, color: 'var(--osd-accent)', padding: '10px 18px' }}>
              YOUNG INNOVATORS' FAIR // 6 NOV
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};

// ─── Page 27 · Closing ───────────────────────────────────────────────────────
const Closing: Page = () => (
  <div style={fill}>
    <Styles />
    <Chrome right="THANK YOU //" />
    <Rings size={720} style={{ left: -260, top: -300 }} />
    <Halftone
      style={{
        right: 100,
        bottom: 140,
        width: 360,
        height: 120,
        maskImage: 'linear-gradient(100deg, black 20%, transparent 95%)',
        WebkitMaskImage: 'linear-gradient(100deg, black 20%, transparent 95%)',
      }}
    />
    <div
      style={{
        position: 'absolute',
        inset: 0,
        padding: '150px 100px 110px',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <Tag color="var(--osd-accent)">// THE WHOLE LOOP, IN ONE SENTENCE</Tag>
      <h2
        style={{
          fontFamily: 'var(--osd-font-display)',
          fontSize: 96,
          lineHeight: 1.04,
          margin: '36px 0 0',
          maxWidth: 1620,
          fontWeight: 400,
        }}
      >
        ASIRIVE CORTEX FILLS WHAT THE CANE CANNOT FEEL —{' '}
        <span style={{ color: 'var(--osd-accent)' }}>
          NAVIGATION THAT IS HANDS-FREE, AFFORDABLE AND DIGNIFIED.
        </span>
      </h2>
      <div style={{ marginTop: 'auto' }}>
        <LoopRail active={5} />
        <div
          style={{
            marginTop: 70,
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'flex-end',
            borderTop: `1px solid ${palette.line}`,
            paddingTop: 30,
          }}
        >
          <div>
            <div
              style={{
                fontFamily: 'var(--osd-font-display)',
                fontSize: 66,
                lineHeight: 1,
              }}
            >
              <span style={{ color: palette.text }}>ASIRIVE</span>{' '}
              <span style={{ color: 'var(--osd-accent)' }}>CORTEX</span>
            </div>
            <div
              style={{
                marginTop: 14,
                fontFamily: font.mono,
                fontSize: 17,
                letterSpacing: '0.12em',
                color: palette.muted,
              }}
            >
              HAZIQ SHAH · MUHAMMAD IRFAN NUAFAL · ERYNA NATASHA — ADMIRALTY SECONDARY SCHOOL
            </div>
          </div>
          <a
            href="https://www.asirive.com/cortex"
            target="_blank"
            rel="noreferrer"
            style={{
              fontFamily: font.mono,
              fontSize: 18,
              letterSpacing: '0.14em',
              color: 'var(--osd-accent)',
              textDecoration: 'none',
            }}
          >
            ASIRIVE.COM/CORTEX
          </a>
        </div>
      </div>
    </div>
  </div>
);

// ─── Page 28 · Video showcase ────────────────────────────────────────────────
const Showcase: Page = () => (
  <div style={fill}>
    <Styles />
    <Chrome />
    <Rings size={620} style={{ right: -220, bottom: -280 }} />
    <div
      style={{
        position: 'absolute',
        inset: 0,
        padding: '150px 100px 100px',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <Tag color="var(--osd-accent)">// 09 SEE IT WORK — VIDEO SHOWCASE</Tag>
      <h2
        style={{
          fontFamily: 'var(--osd-font-display)',
          fontSize: 92,
          lineHeight: 0.98,
          margin: '22px 0 44px',
        }}
      >
        DON'T TAKE OUR WORD FOR IT. <span style={{ color: 'var(--osd-accent)' }}>WATCH.</span>
      </h2>
      <div style={{ display: 'flex', gap: 60, flex: 1, minHeight: 0 }}>
        <a
          href="https://www.youtube.com/watch?v=vgvTApfXBPM"
          target="_blank"
          rel="noreferrer"
          style={{
            flex: 1.6,
            position: 'relative',
            display: 'block',
            border: `1px solid ${palette.line}`,
            overflow: 'hidden',
            background: '#000',
            aspectRatio: '16 / 9',
            alignSelf: 'center',
            width: '100%',
            textDecoration: 'none',
          }}
        >
          <img
            src={videoThumb}
            alt="Asirive Cortex — video showcase thumbnail"
            style={{
              position: 'absolute',
              inset: 0,
              width: '100%',
              height: '100%',
              objectFit: 'cover',
            }}
          />
          <div
            style={{
              position: 'absolute',
              inset: 0,
              display: 'grid',
              placeItems: 'center',
              background: 'rgba(10,10,8,0.18)',
            }}
          >
            <div
              style={{
                width: 120,
                height: 120,
                borderRadius: '50%',
                background: 'var(--osd-accent)',
                display: 'grid',
                placeItems: 'center',
                color: palette.bg,
                fontSize: 44,
                paddingLeft: 8,
              }}
            >
              ▶
            </div>
          </div>
          <div
            style={{
              position: 'absolute',
              left: 0,
              bottom: 0,
              right: 0,
              background: 'rgba(10,10,8,0.82)',
              padding: '12px 22px',
              fontFamily: font.mono,
              fontSize: 16,
              letterSpacing: '0.1em',
              color: 'var(--osd-accent)',
            }}
          >
            YOUTUBE.COM/WATCH?V=VGVTTAPFXBPM — CLICK TO PLAY
          </div>
        </a>
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
          <Tag>WHAT YOU'LL SEE</Tag>
          <div style={{ marginTop: 24 }}>
            {[
              'Cortex guiding a real walk, start to stop',
              'open-ear voice directions in action',
              'the cane stays in hand the whole time',
            ].map((t, i) => (
              <div key={t}>
                <Rule />
                <div style={{ display: 'flex', gap: 24, padding: '20px 0', alignItems: 'baseline' }}>
                  <span style={{ fontFamily: font.mono, fontSize: 18, color: 'var(--osd-accent)' }}>
                    {String(i + 1).padStart(2, '0')}
                  </span>
                  <span style={{ fontSize: 25, lineHeight: 1.4 }}>{t}</span>
                </div>
              </div>
            ))}
            <Rule />
          </div>
          <a
            href="https://www.youtube.com/watch?v=vgvTApfXBPM"
            target="_blank"
            rel="noreferrer"
            style={{
              marginTop: 40,
              display: 'inline-block',
              background: 'var(--osd-accent)',
              color: palette.bg,
              fontFamily: font.mono,
              fontSize: 19,
              letterSpacing: '0.1em',
              padding: '16px 30px',
              textDecoration: 'none',
              width: 'fit-content',
            }}
          >
            ▶ WATCH ON YOUTUBE
          </a>
        </div>
      </div>
    </div>
  </div>
);

// ─── Page 29 · Mentors & thanks ──────────────────────────────────────────────
const Mentors: Page = () => {
  const cards = [
    {
      role: 'IVP MENTOR',
      names: ['ASST PROF ERKAN KAYACAN'],
      note: 'Assistant Professor, School of Mechanical & Aerospace Engineering — NTU',
    },
    {
      role: 'TEACHER MENTORS — ADSS',
      names: ['MS NUR SYAZANA BINTE RASHID', 'MS FLORENCE KUEK', 'MR DESMOND NG'],
      note: 'Admiralty Secondary School — guided every iteration of this deck',
    },
    {
      role: 'FIELD PARTNER',
      names: ['SAVH'],
      note: 'Singapore Association of the Visually Handicapped — thank you for your valuable inputs across three testing sessions.',
    },
  ];
  return (
    <div style={fill}>
      <Styles />
      <Chrome />
      <Halftone
        style={{
          right: 100,
          top: 150,
          width: 300,
          height: 100,
          maskImage: 'linear-gradient(100deg, black 20%, transparent 95%)',
          WebkitMaskImage: 'linear-gradient(100deg, black 20%, transparent 95%)',
        }}
      />
      <div
        style={{
          position: 'absolute',
          inset: 0,
          padding: '150px 100px 100px',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <Tag color="var(--osd-accent)">// 10 WITH THANKS</Tag>
        <h2
          style={{
            fontFamily: 'var(--osd-font-display)',
            fontSize: 92,
            lineHeight: 0.98,
            margin: '22px 0 20px',
          }}
        >
          WE DIDN'T GET HERE ALONE.
        </h2>
        <p style={{ margin: 0, fontSize: 26, color: palette.muted, maxWidth: 1200 }}>
          user-first means listening to more than users — these are the people who kept us
          honest at every stage.
        </p>
        <div style={{ display: 'flex', gap: 24, marginTop: 36, flex: 1, minHeight: 0 }}>
          {cards.map((c, i) => (
            <div
              key={c.role}
              style={{
                flex: 1,
                display: 'flex',
                flexDirection: 'column',
                border: `1px solid ${palette.line}`,
                overflow: 'hidden',
              }}
            >
              <div
                style={{
                  background: i === 0 ? 'var(--osd-accent)' : palette.surfaceHi,
                  color: i === 0 ? palette.bg : 'var(--osd-accent)',
                  fontFamily: font.mono,
                  fontSize: 18,
                  letterSpacing: '0.14em',
                  padding: '18px 24px',
                }}
              >
                {c.role}
              </div>
              <div
                style={{
                  padding: '22px 26px 0',
                  fontFamily: 'var(--osd-font-display)',
                  fontSize: 34,
                  lineHeight: 1.12,
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 12,
                }}
              >
                {c.names.map((n) => (
                  <span key={n}>{n}</span>
                ))}
              </div>
              <div
                style={{
                  marginTop: 12,
                  padding: '0 26px 24px',
                  fontSize: 21,
                  lineHeight: 1.4,
                  color: palette.muted,
                }}
              >
                {c.note}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

// ─── Slide export ────────────────────────────────────────────────────────────
export const meta: SlideMeta = {
  title: 'Asirive Cortex — IvP 2026 (User-First or User-Fail?)',
};

export default [
  Cover,
  Contents,
  Challenge,
  DividerEmpathize,
  BillionStat,
  SavhResearch,
  TradeOff,
  DividerDefine,
  ProblemStatement,
  DividerResearch,
  Alternatives,
  TheGap,
  DividerIdeate,
  DesignRules,
  DividerPrototype,
  WhatItIs,
  FiveSpecialists,
  ArchHybrid,
  ArchVoice,
  ArchStates,
  CaneMatrix,
  DividerTest,
  ThePivot,
  Iterations,
  Proof,
  Acknowledgment,
  Showcase,
  Mentors,
  Closing,
] satisfies Page[];
