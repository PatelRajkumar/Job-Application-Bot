# Chiral Landing Page — Senior Infrastructure Tooling Audit

**Scope:** Full source review — `index.astro`, `global.css`, all component files, `CLAUDE.md`  
**Lens:** Principal designer + senior DevOps operator + frontend architect  
**Standard:** "Would this increase or decrease confidence in letting this tool near production infrastructure?"

---

## EXECUTIVE VERDICT

**Does this page earn trust?** Conditionally. More than most developer tool landing pages, but with specific failure modes that will cause a non-trivial percentage of target operators to hesitate at the install step.

**Would a skeptical technical operator install this?** The hesitation point is not the page design — it is a specific combination of unverifiable proof signals, an ambiguous "about" section, and the install command structure. A skeptical operator will arrive at the TrustBlock, nod, read the terminal output, and then pause at the About section and feel the absence of community proof, GitHub star counts, or any signal that this tool exists outside this page.

**Does this feel like serious infrastructure tooling?** Partially. The palette, typography, and copy discipline are largely correct. The macro architecture is sound — Trust before Features is a meaningful differentiator. The failure is in the motion layer, specific implementation details, and one structural omission that is not a small fix.

**Single largest trust failure:** The `drift` animation on hero glows. Two large, semi-opaque amber and orange blobs moving across the viewport on a 20-second loop is the single biggest signal inconsistency in the design. Everything else on the page communicates "precise, mechanical, stable." Those blobs communicate "trendy SaaS starter template." The senior DevOps engineer sees this and feels a dissonance they can't always articulate but will subconsciously act on.

**Strongest aspect:** The copy. CLAUDE.md's copy rules are being followed. The problem narrative in Section 3 — particularly "In n8n CE, a saved, activated workflow is a live workflow. There is no staging buffer. There is no 'are you sure?'" — is the most operationally credible paragraph on the page. It will read as genuine to the target audience because it describes a specific, real behavior that only someone who has actually operated n8n CE would know.

---

## THINGS THAT REDUCE TRUST

### 1. The hero glow animation (`drift` keyframe)
**Issue:** Two enormous blobs (`120vw × 100vh` and `100vw × 100vh`) animated with `ease-in-out` on a 20-second loop, using amber and `#ff5e00`. They cover the entire viewport behind the hero content.  
**Why it reduces trust:** The `drift` animation is the visual vocabulary of venture-backed SaaS marketing (Linear, Vercel's homepage variants, Luma). It reads as "startup aesthetic theater" to experienced engineers. Infrastructure tools — Depot, Fly.io, Infisical, the actual tools listed as references — do not use drifting ambient glows. This animation pattern says: "we saw this on another landing page and it looked cool." More critically, the amber glow matches the accent color, which is supposed to signify warnings and operational significance. A pulsing amber blob in the hero dilutes the warning semantics of amber across the rest of the page.  
**Severity:** Critical  
**Recommendation:** Remove both `.hero-glow` elements entirely. Replace with: nothing, or a single static 1px horizontal rule below the nav, or a very subtle radial gradient (`background: radial-gradient(ellipse 60% 40% at 50% -10%, rgba(240,165,0,0.04) 0%, transparent 100%)`) — static, not animated, opacity max 0.04. The `#ff5e00` orange has no place in a design with a defined palette. It is a hardcoded hex value that violates CLAUDE.md's own CSS variable rule.

---

### 2. The `TerminalDemo` typing animation speed and mechanism
**Issue:** `CHARS_PER_TICK = 4` at `TICK_MS = 16` (~240 chars/second, completing in ~250ms). Mechanistically, this runs on a `setInterval` at 16ms, not on any event-driven timing. The cursor blinks with `step-end` timing (correct), but the text reveal itself uses a simple slice — it renders entire character groups simultaneously, not one character at a time.  
**Why it reduces trust:** At this speed, the text appears to materialize rather than type. The experience does not resemble a real terminal. Real terminals output at line granularity with perceptible timing per line, especially for operations involving network calls. At 240 chars/second, `chiral diff` would be appearing to complete in about one second for 16 lines of output — faster than any real CLI that makes API calls. The psychological effect is that this reads as a movie prop terminal, not an actual tool output. A skeptical operator will notice the speed does not match the implied operation.  
**Severity:** High  
**Recommendation:** Change the animation to output **line by line** with a `setTimeout` per line, each spaced 120–200ms apart. No character-by-character for the output lines — only for the initial command prompt (`$ chiral diff...`). This matches how real terminals work: the command types, then the process runs, then output appears in discrete chunks. Additionally, add a 400ms pause after the command before output begins — simulating network/API latency. This single change would make the terminal feel operational rather than theatrical.

---

### 3. The `amber-pulse` animation on trust icons and step numbers
**Issue:** Icons in TrustBlock (Lock, Eye, History) and step counters in Steps have `.pulse` class — `amber-pulse` at `4s ease-in-out infinite`, cycling opacity 1→0.65→1.  
**Why it reduces trust:** Pulsing icons is a growth-hacking UX pattern used to draw attention. On an infrastructure tool page, pulsing "Read-only by default," "See exactly what changes," and "Undo what you push" sends the wrong signal. These are guarantees — they should be stated with the confidence of certainty, not pulsed like a notification badge. Pulsing = "pay attention here" = implies these qualities are uncertain and need to be marketed. Operational certainty is communicated through stillness, not animation.  
**Severity:** High  
**Recommendation:** Remove `.pulse` from every `.trust-icon` and `.step-number`. Icons should be static. If visual emphasis is needed, increase icon size or use a heavier border on the step counter.

---

### 4. The `PullQuote` hover interaction
**Issue:** `border-left-color` transitions from `var(--color-border)` to `var(--color-accent)` on hover for all three blockquotes.  
**Why it reduces trust:** These are attributions from forums and blogs. They are evidence. Turning them amber on hover makes them feel like interactive marketing elements rather than cited sources. The hover behavior implies interactivity where there is none — nothing happens when you click. More critically, these quotes are anonymous community complaints: `"n8n community forum"`, `"r/n8n"`, `"n8n automation blog"`. The hover treatment elevates anonymous forum posts to the visual weight of verified testimonials.  
**Severity:** Medium  
**Recommendation:** Remove the hover transition from `.pull-quote`. Make them static. The border-left at `var(--color-border)` is correct — it gives structure without weight. Separately, consider whether these attribution sources are credible enough. `"n8n automation blog"` with quote `"Hope is not a deployment strategy"` reads like it was written as an illustrative example rather than sourced. If it's a real source, link it. If not, cut it and replace with a more specific attribution.

---

### 5. The install command structure
**Issue:** `sh -c "$(curl -sSfL https://chiral.sh/install)"` is the displayed install command.  
**Why it reduces trust:** `curl | sh` patterns are a known security red flag in the infrastructure community. This audience reads HN. They know the discussions. The `-f` flag (fail silently on server error) with `-sS` (silent but show errors) is correct practice, but the wrapping structure `sh -c "$()"` is subtly different from the more common `bash <(curl ...)` or the explicitly-inspectable `curl ... | sh` and this difference is not explained. More importantly, there is zero copy near the install command about inspectability: no mention that the install script is open, no link to the raw script URL, no reassurance about what it does. A security-conscious operator will hesitate.  
**Severity:** High  
**Recommendation:** Below the install command, add a single line: `# Install script: chiral.sh/install.sh` as muted, copyable text — or a hyperlink that opens the raw install script. This is standard practice for trusted CLI tools (Homebrew, rustup, fnm). It says: "we know you're going to look at this. Here it is." Add it inline in the `InstallCommand` component, not in a separate section.

---

### 6. The About section — ghost of a founder, no verifiable signal
**Issue:** Section 7 is three paragraphs of first-person claims with zero verifiable proof. "Built by someone who has operated self-hosted n8n CE." "Active in community.n8n.io →" — links to the n8n community root, not to a specific profile.  
**Why it reduces trust:** "Built by someone who has operated" is the kind of claim anyone can make. The forum link goes to `community.n8n.io` — not to a specific profile URL. There is no GitHub handle visible on the page (the footer has a GitHub link but it goes to the repo, not the author). This section is supposed to answer: "will this tool be maintained?" and "does this person actually understand n8n CE operations?" It fails both questions. The link to "community.n8n.io" looks like a broken or fabricated attribution.  
**Severity:** Critical  
**Recommendation:** Replace the community.n8n.io link with the specific author profile URL. Add one concrete credibility signal: either a specific forum thread where the author discussed this problem, or a GitHub profile link. The sentence "Active in community.n8n.io →" should read "Purvesh on community.n8n.io →" with a link to the actual profile. Remove the anonymizing "built by someone who has" — just say "I." First-person directness signals accountability, which is a trust signal.

---

### 7. The comparison table — "rollback" row is self-damaging
**Issue:** "One-command rollback" shows `✗ (paid)` for Chiral Free. The TrustBlock above it says "Undo what you push — every push is reversible via `chiral rollback`. Git-backed." This is contradicted five sections later.  
**Why it reduces trust:** A skeptical reader will notice this inconsistency. The TrustBlock positions rollback as a core safety guarantee ("Undo what you push"). The comparison table then shows rollback as a paid feature. The cognitive dissonance here is significant: the "trust" section appears to be making promises that the free tier doesn't keep. This is the most precise kind of damage — it makes the entire trust section feel like marketing copy rather than honest specification.  
**Severity:** Critical  
**Recommendation:** The TrustBlock copy must be accurate to the free tier, or the callout must explicitly state the tier boundary. Options: (a) change TrustBlock "Undo what you push" copy to be accurate — e.g., "Every push is git-committed. Rollback on Team tier." (b) Keep rollback in the free tier. (c) Add a `(Team)` suffix to the TrustBlock item matching the style of the comparison table. Do not leave this inconsistency in the page. This is a honesty-at-first-glance failure.

---

## THINGS THAT FEEL AMATEUR

### Typography: two font families for monospace
**Issue:** The codebase uses three typefaces total but handles monospace inconsistently: `Departure Mono` is used for the terminal body, step numbers, wordmark, button primary, eyebrow, and install command. `IBM Plex Mono` (300 weight) is used for inline `<code>` elements. The `global.css` sets `code { font-family: 'IBM Plex Mono' }` but `TerminalBlock` and `InstallCommand` explicitly set `Departure Mono`. The result: inline `chiral diff` in body copy renders in IBM Plex Mono Light; the same string in a terminal renders in Departure Mono. This creates two visual registers for the same semantic element.  
**Why it signals amateur:** Experienced typographers pick one monospace for an entire system. Having two monospace families — one for "display terminal" and one for "inline code" — is a decision that needs to be either intentional and documented, or resolved. It isn't documented in CLAUDE.md as intentional. When a senior engineer sees `chiral diff` inline looking different from `chiral diff` in the terminal, they register "inconsistency" before they can name why.  
**Fix:** Make a decision. Either: (a) use `Departure Mono` everywhere monospace appears, including inline code — this gives the brand a unified terminal voice, (b) use `IBM Plex Mono` everywhere and use `Departure Mono` only for the wordmark. Currently, the split is arbitrary.

---

### The macOS traffic light dots on all terminals
**Issue:** Every terminal component — `TerminalDemo`, `TerminalBlock`, `InstallCommand` — renders three colored dots: red (`--color-error`), amber (`--color-accent`), green (`--color-success`). This is a macOS window chrome pattern.  
**Why it signals amateur:** This is the most overused "developer aesthetic" element in marketing. Every SaaS that wants to look technical uses these dots. They are visual shorthand for "this is a terminal" aimed at a general audience. The target audience for Chiral doesn't need three colored circles to understand they're looking at a terminal. More critically, the dots are decorative — they do nothing. On an operational tool page, non-functional UI elements read as theater. Fly.io (cited as a reference) dropped the dots. Depot uses a plain header bar with a path label. Both look more operationally serious.  
**Fix:** Remove the three dots from all terminal headers. Replace with a left-aligned `$` prompt character in muted color, or a path string like `~/workflow-repo`, or nothing — just a top border and background is sufficient.

---

### `border-radius: 6px` on terminals — too soft
**Issue:** Terminal containers have `border-radius: 6px`. The button has `border-radius: 4px`. The callout has `border-radius: 4px`. The terminal is the most operationally serious element on the page and has the highest border-radius.  
**Why it signals amateur:** Rounding is an aesthetic warmth signal. The softer the corners, the friendlier and less serious the component feels. Infrastructure tools tend toward `border-radius: 2px` or `0` for terminal/code blocks — this matches the visual language of actual terminals and code editors, which use sharp or nearly-sharp corners. A 6px radius on a terminal makes it feel like a stylized marketing prop.  
**Fix:** Change `.terminal { border-radius: 2px }` and `.terminal-demo { border-radius: 2px }`. Keep the callout and button at 4px — those are UI elements, not terminal surfaces.

---

### The `Step` component's number counter uses `.pulse`
**Issue:** The `step-number` div has class `pulse` applied, so the amber-bordered step counter breathes opacity on an infinite loop.  
**Why it signals amateur:** Numbered step indicators in onboarding flows are navigation anchors, not attention-grabbers. Pulsing a step counter implies the user can't find it without animation. It's a visual anxiety response — "what if they miss it?" — that experienced designers don't have because they trust their hierarchy. The pulse also desynchronizes across the three steps, so you get three circles with different opacity phases simultaneously, which creates visual noise.  
**Fix:** Remove `.pulse` from `Step`. Add `margin-top: var(--space-1)` to align the counter with the label top edge if needed.

---

### The `PullQuote` attribution sources lack specificity
**Issue:** Attributions are `"n8n community forum"`, `"r/n8n"`, and `"n8n automation blog"`. No usernames, no post titles, no links, no dates.  
**Why it signals amateur:** Social proof without attribution details is not social proof — it is assertion. A technical audience that reads documentation carefully (as specified in CLAUDE.md) will look for verifiability. "n8n community forum" could mean anything. "r/n8n" with no link could be invented. Senior engineers apply the same skepticism to unlinked quotes that they apply to unlinked benchmarks. The third quote specifically — `"Hope is not a deployment strategy"` attributed to `"n8n automation blog"` — reads as a constructed rhetorical flourish, not a genuine user voice.  
**Fix:** Link every quote to its source. If sources don't exist or can't be attributed, replace with specific community members who have consented to being named, or remove the quotes entirely and use a single, specific incident narrative from a real case.

---

## DEVELOPER CREDIBILITY ANALYSIS

### What works operationally
The copy demonstrates genuine n8n CE operational knowledge in specific, verifiable ways:

1. **"n8n's built-in version IDs regenerate on every save."** This is a real, specific behavior that only someone who has actually used n8n CE would know. It is the kind of detail that causes engineers to lower their shields.
2. **"Content fingerprinting — it compares what the workflow actually does, not what its ID says."** This is a correct description of the actual problem. SHA-256 fingerprinting of workflow content vs. version ID comparison is a real architectural distinction.
3. **"Credential remapping: stripe_staging → stripe_production ✓"** — Showing credential remap as part of push output is operationally specific. This is a genuine pain point.
4. **The diff output format** (separator lines, `MODIFIED (2)`, `UNCHANGED (14 workflows)`, node-level change descriptions) feels like real CLI output, not a marketing approximation.

### What raises flags

**"No false positives after a push. If `chiral diff` says something changed, something changed."** — This is a strong claim that demands evidence. Is this testable? Is there a test suite visible in the GitHub repo? A senior engineer reading this will immediately think "how does this handle n8n's edge cases around versioned subworkflows, pinned execution data, and disabled nodes?" The claim should either be scoped ("for activated workflow definitions") or supported with a link to the implementation.

**"Every push is git-committed. Who pushed, what changed, when."** — The comparison table shows "Git-backed history ✓ auto-commit" for Chiral Free. But nowhere on the page does it explain the git architecture. Does Chiral manage a separate git repo? Does it commit to the user's existing repo? This is non-trivial for production operators who care about audit trail ownership. The absence of this explanation makes the claim feel like marketing copy.

**The RBAC feature block:** `"Production pushes require RBAC clearance. Request access: chiral team --request-access"`. The word "RBAC" implies role-based access control infrastructure — JWT validation, permission scopes, a user management system. For a "not venture-backed, no hosted dashboard" CLI tool, this raises architectural questions. How does RBAC work for a CLI tool that doesn't have a central auth service? Is it local config? Is there a hosted auth component? This question is not answered anywhere on the page, and an infrastructure-conscious operator will notice.

**"It is not AI-powered."** — This is a good negative claim, and it will land positively with the target audience. It directly addresses the fear that the tool is vaguely LLM-powered in ways that create unpredictable behavior. Keep this.

---

## TERMINAL CTA & INSTALL FLOW AUDIT

### Install command text
`sh -c "$(curl -sSfL https://chiral.sh/install)"`

**Typography:** Rendered in `Departure Mono` at `--text-mono` (0.9375rem). Correct font choice. Size is appropriate.

**Visibility:** The install command appears in three locations: hero CTA, Get Started step 1, Final CTA. This repetition is structurally correct.

**Copy button:** The `CopyButton` component is a 2rem × 2rem icon button with a 1px border. It is present and functional. The button label is `"Copy install command"` (aria-label). After copy, it shows green (`--color-success`) state.

**Critical issues:**

1. **No script inspection link.** This is the single most important missing element for security-conscious operators. Add a line below the command: `<a href="https://chiral.sh/install.sh">View install script ↗</a>` in `--color-muted`. This is what rustup, Homebrew, and fnm all do. Its absence is noticed.

2. **The command itself scrolls on mobile.** `white-space: nowrap` with `overflow-x: auto` is technically correct, but on narrow mobile screens, the command renders partially, with the copy button potentially outside view. The `scrollbar-width: none` hides the overflow indicator, making the truncation invisible. An operator on mobile (checking on their phone before installing on a server) may see `sh -c "$(curl -sSfL https://` and not realize there's more. Recommendation: add a `…` indicator at the right edge if the command overflows, or consider a two-line render on narrow viewports.

3. **No "read-only to start" reassurance adjacent to the install command.** The Callout in the Get Started section (`"chiral diff never writes to your n8n instance. It only reads."`) is correctly placed in the onboarding flow but it appears three sections after the hero install command. A risk-averse operator who stops at the hero install command and doesn't scroll will not have seen this reassurance before they're asked to pipe a script to their shell. Recommendation: Add a single line below the hero install command: `chiral diff is read-only. Nothing is written until you explicitly run push.` in `--color-muted` at `--text-sm`.

### Terminal typing animation (hero TerminalDemo)
As detailed above, the timing is too fast. Additionally:

- **The `aria-hidden="true"` on the entire terminal demo is correct** — it is decorative/animated. The `sr-only` fallback paragraph is present. This is good accessibility practice.
- **The cursor** uses `█` (block cursor, U+2588) with `step-end` blink. Correct — this matches real terminal cursor behavior.
- **The font is `Departure Mono`** — correct for terminal surfaces.
- **No title/path in the terminal bar** — just three dots. See Terminal Dots issue above.

---

## VISUAL HIERARCHY & INFORMATION ARCHITECTURE

### Section ordering: mostly correct, one gap
The 8-section order follows CLAUDE.md exactly, and the Trust section before Feature blocks is the right call. However, there is a hierarchy gap between what is promised at the top and what is delivered in detail:

**What lands early and clearly:**
- Read-only by default ✓
- Dry-run preview ✓
- Git-backed rollback ✓ (but contradicted by table, see above)

**What does not appear until late:**
- The RBAC/permission system — this is Section 4 (Feature Block 3), which is the right position, but it is the most complex trust question (who controls production access?) and it gets the shallowest treatment. One terminal block and three paragraphs do not sufficiently explain how production gating actually works.
- Pricing clarity — the comparison table is Section 5 of 8. On most infrastructure tool pages, pricing clarity (even "free, with this limitation") needs to be visible much earlier. An operator who reaches the About section (7 of 8) without understanding pricing will have been managing uncertainty the entire scroll.

**Recommendation:** Add a one-line pricing signal below the hero CTA group: `Free for single-project use. Team tier for RBAC + rollback.` in `--color-muted` at `--text-sm`. This eliminates pricing anxiety before it can accumulate.

### Cognitive flow issues
The page moves from an anxiety-inducing headline ("You're one push away from breaking a client's live automation") directly to a terminal demo, then to a Trust section that reassures. This ordering is counterintuitive: you create fear, show the tool, then explain why it's safe. The problem narrative (Section 3) reinforces the fear after the trust section has already addressed it, which undoes some of the trust work. The narrative logic should be: fear → trust → how → proof. Currently it is: fear → tool → trust → more fear → how it works. Consider either moving the Problem section before the TrustBlock, or reframing it as "here's why this problem exists in n8n" rather than re-amplifying the fear.

---

## MOTION & INTERACTION DESIGN AUDIT

### Hero glow — `drift` animation
- Timing: 20s ease-in-out infinite alternate
- Transform: `translate(20vw, 15vh) scale(1.15)`
- Opacity: 0.08
- **Psychological effect:** Floaty, magical, cinematic. `ease-in-out` with a scale transform creates an organic, living quality. Infrastructure tools should feel static, not alive.
- **Trust damage:** Signals "startup landing page" to anyone who has browsed the SaaS ecosystem in the last three years. The 20s loop means it is visible at normal reading speed.
- **Fix:** Delete the animation. Delete both `.hero-glow` divs. Replace with the static radial gradient described above, or nothing.

### TrustBlock icons — `amber-pulse`
- Timing: 4s ease-in-out infinite
- Opacity: 1 → 0.65 → 1
- **Psychological effect:** Draws attention continuously. Infrastructure guarantee icons should radiate certainty, not attract.
- **Fix:** Delete `.pulse` from icon containers.

### Step numbers — `amber-pulse`
- Same animation, same damage.
- **Fix:** Delete `.pulse` from `.step-number`.

### PullQuote — border-left hover
- Timing: 0.2s ease
- Color: `--color-border` → `--color-accent`
- **Psychological effect:** Makes evidence feel interactive and promotional.
- **Fix:** Remove hover behavior from `.pull-quote`.

### Terminal — border-color hover
- `TerminalBlock` has `transition: border-color 0.15s ease` and `.terminal:hover { border-color: var(--color-muted) }`.
- **Assessment:** This is the most defensible hover behavior in the entire system. Terminals responding slightly to hover is an acceptable affordance — it reinforces that the content is selectable and real. Keep this.

### fade-up scroll animation
- `translateY(16px)` → `0` over 0.3s ease-out, or via `animation-timeline: view()` with `entry 0% entry 30%` range.
- **Assessment:** Acceptable. 16px is a small travel distance, 0.3s is a short duration, ease-out is the correct easing for entrance. This does not feel cinematic. Keep it. The progressive enhancement fallback (IntersectionObserver for browsers without animation-timeline) is correctly implemented.

### Button hover — opacity: 0.85
- **Assessment:** Minimal and functional. Acceptable. For a primary amber button, a slightly brighter amber on hover would be more operational (hover = "active, ready") than opacity reduction (hover = "dimming"). Consider `filter: brightness(1.08)` instead, but this is low priority.

---

## CODE-LEVEL IMPLEMENTATION CRITIQUE

### Issue 1: Hardcoded hex `#ff5e00` in `index.astro`
**Evidence:** Line 255: `background: #ff5e00;`  
**Root cause:** This color has no design token. It is not in `global.css`. It is not in CLAUDE.md's color palette. CLAUDE.md explicitly says "CSS variables only — no hardcoded hex in component files."  
**Fix:** Either define `--color-glow-warm: #ff5e00` in global tokens (if keeping the glow) or delete the `.hero-glow-2` element entirely (recommended).

### Issue 2: `TerminalDemo` is `aria-hidden="true"` but the `sr-only` fallback has the same content
**Evidence:** Lines 43, 53 of `TerminalDemo.tsx`  
**Assessment:** This is correct, not a bug. The animated terminal is decorative; screen readers get the static text. No change needed.

### Issue 3: `InstallCommand` has two scroll containers nested
**Evidence:** `.install-wrap { overflow-x: auto }` and `.install-cmd { overflow-x: auto }` — both the wrapper and the `<pre>` have overflow-x: auto. This creates redundant scroll contexts.  
**Fix:** Remove `overflow-x: auto` from `.install-cmd`. Keep it only on `.install-wrap`. The hidden scrollbar is on `.install-cmd` anyway, so the scroll is invisible.

### Issue 4: `PullQuote` passes all `Astro.props` to `<blockquote>` including `data-stagger`
**Evidence:** Line 7 of `PullQuote.astro`: `{...Astro.props}` — this spreads all props including `data-stagger` and `attribution` onto the DOM element. `attribution` is not a valid HTML attribute.  
**Fix:** Explicitly spread only valid HTML attributes, or filter out component-specific props before spreading:
```astro
<blockquote class="pull-quote animate-in" data-stagger={Astro.props['data-stagger']}>
```

### Issue 5: The `FeatureBlock` uses `set:html` for the `body` prop
**Evidence:** Line 18 of `FeatureBlock.astro`: `<p set:html={body} />`  
**Assessment:** `set:html` in Astro bypasses escaping. The `body` prop contains `<code>`, `<br>` tags. This is author-controlled content (not user input), so it is not an XSS vector in this context. However, it means body copy must be authored as raw HTML, which is fragile. Consider using a `<slot name="body">` instead of a string prop with embedded HTML.

### Issue 6: Animation delay implementation — dual system
**Evidence:** `global.css` lines 306–320 define `.animate-in` with CSS `transition-delay: var(--animation-delay, 0ms)` for non-scroll-animation browsers, and `animation-delay: var(--animation-delay, 0ms)` for scroll-driven animation. But elements also have `data-stagger` attributes that the `BaseLayout` script converts to inline `style.transitionDelay`. The `--animation-delay` CSS variable is set via inline `style="--animation-delay: 0ms"` in `FeatureBlock`, but the `BaseLayout` script reads `data-stagger` and sets `style.transitionDelay` directly, which does not feed the CSS variable.  
**Impact:** Elements in `FeatureBlock` have both `style="--animation-delay: 0ms"` and `data-stagger` attributes. The BaseLayout script overrides `style.transitionDelay` from `data-stagger`, ignoring `--animation-delay`. These two systems are redundant and potentially conflicting. In browsers with `animation-timeline: view()` support, the `animation-delay` CSS variable is used (from inline style). In fallback browsers, the JS sets `style.transitionDelay` from `data-stagger`. Both values appear to be the same in practice, but the architecture is duplicated.  
**Fix:** Pick one system. The CSS variable approach (`--animation-delay`) is cleaner. Remove `data-stagger` attributes from markup and set the CSS variable only via inline style.

---

## CONVERSION FRICTION ANALYSIS

### Friction point 1: Install command safety — HIGH FRICTION
A skeptical technical operator sees `sh -c "$(curl -sSfL https://chiral.sh/install)"`. This is the Moment of Decision. The page has not yet told them: what the script does, where they can read it, whether it requires sudo, what it installs and where, and whether there are alternative install methods (Homebrew, npm, cargo, pre-built binary). For a production infrastructure tool used by security-aware teams, this is a significant gap.  
**Resolution:** Add a "How does install work?" accordion or micro-FAQ inline, or a `View script source` link. Consider adding `# No sudo required. Installs to ~/.local/bin` as a comment-style annotation below the command.

### Friction point 2: Free tier limits — MEDIUM FRICTION
"Free for single-project use, indefinitely" is in the comparison table but not in the hero or CTA sections. An operator's first concern is "is this going to try to charge me after I'm dependent on it?" The pricing clarity is buried.

### Friction point 3: Maintainer risk — HIGH FRICTION
The About section does not answer: How long has this been maintained? Is there a changelog? Is there a v1.0 or is this pre-release? A GitHub repo link exists but there's no star count, no release count, no activity signal visible on the landing page. An operator's fear — "this maintainer may disappear" — is directly correlated with visible activity signals.  
**Resolution:** Add one concrete signal to the About section: "v0.x.x — actively maintained. Changelog →" or the current GitHub release version pulled at build time.

### Friction point 4: The email capture fallback — MEDIUM FRICTION
`"Get notified →"` button label combined with `"No spam. Unsubscribe any time."` note is adequate, but `"You're on the list. We'll email when something ships."` success state is ambiguous. "Something ships" — what? Another version? A new feature? A different product? This reads like an early-stage startup hedging on a roadmap. For infrastructure operators, "something ships" is not reassuring.  
**Resolution:** Change to: `"You'll be notified for v1.0 release and major updates. No spam."` — specific, scoped, credible.

### Friction point 5: No secondary trust evidence — HIGH FRICTION
There are no GitHub stars visible, no user count, no "X teams using Chiral," no specific production usage claims, no testimonials with names. The only social proof is three unlinked forum quotes. For a tool asking operators to run an install script on servers hosting client production workflows, the absence of any verifiable adoption signal is a high-friction gap.  
**Resolution:** At minimum, show the GitHub star count (build-time fetch or a GitHub badge). A single named user quote with their actual n8n community profile would be worth more than all three anonymous pull quotes combined.

---

## FINAL PRIORITIZED FIXES

### Top 5 Critical Issues — Actively Damaging Trust

1. **TrustBlock rollback claim contradicted by comparison table.** The free tier's trust section promises rollback; the table denies it. This is a factual inconsistency at the highest-trust section of the page. Fix immediately.

2. **About section links to community.n8n.io root, not an author profile.** Unverifiable attribution reads as fabricated. Link to the specific community profile or remove the claim.

3. **Hero glow drift animation.** The most visible "startup template" signal on the page. Remove both glow elements.

4. **Install script has no inspection path.** A security-aware operator with no "view script source" link may not install. Add the link.

5. **Pulse animations on trust icons and step counters.** These turn guarantees into promotions. Remove `.pulse` from all non-CTA elements.

---

### Top 5 Highest-Leverage Improvements

1. **Add a hero pricing line.** One line, muted: "Free for single-project use. Team tier adds RBAC and rollback." Eliminates pricing anxiety before it accumulates.

2. **Rework TerminalDemo animation to line-by-line output.** This is the first interactive element operators see. Make it feel like a real tool, not a movie prop.

3. **Link every PullQuote to its source or replace with named, linked testimonials.** Anonymous quotes actively undermine credibility rather than building it.

4. **Add a build-time GitHub star count or release version to the About section.** One data point that says "other people have evaluated this" changes the maintainer-risk calculus.

5. **Add "read-only to start" reassurance directly adjacent to the hero install command.** The Callout in Section 6 is too far from the conversion moment.

---

### Quick Wins — Fast, High-Impact

- Remove `border-radius: 6px` from terminals → use `2px`
- Remove the three traffic-light dots from all terminal headers
- Change `"We'll email when something ships"` → specific release language
- Add `data-stagger` prop-spreading fix in `PullQuote.astro` to avoid invalid HTML attributes
- Remove `overflow-x: auto` from `.install-cmd` (redundant scroll context)
- Remove hardcoded `#ff5e00` — either tokenize or delete

---

### Structural Recommendations — Larger Architecture Changes

1. **Reorder Problem narrative (Section 3) to come before Trust section (Section 2).** The current order creates fear → relief → more fear. The correct operational narrative is: here's the problem → here's why it exists in n8n CE specifically → here's how Chiral addresses it (trust section) → here's how it works (features). The TrustBlock should sit between the Problem and the Feature Blocks, not before the Problem.

2. **Expand the RBAC section to explain the auth architecture.** "Production pushes require RBAC clearance" with no explanation of how RBAC is implemented is a credibility gap for a non-hosted, non-venture-backed CLI tool. Add one paragraph of architecture explanation.

3. **Replace the About section with a specific, named, linked presence.** "Built by someone" is anonymous. "Built by [name], who maintains [specific profile] in the n8n community forum" is accountable. The entire maintainer risk fear exists because the About section protects its author's identity.

---

### Elements That Should Be Removed Entirely

1. **Both `.hero-glow` animated elements** — The drift animation is incompatible with the operational trust register.
2. **The `.pulse` class from trust icons and step counters** — Pulsing guarantees undermines them.
3. **The `PullQuote` hover color transition** — Evidence should not feel interactive or promotional.
4. **`"Hope is not a deployment strategy"` quote** — This reads as a constructed rhetorical flourish, not a real community voice. It lowers the credibility of the other two quotes by association.
5. **The `.hero-glow-2` hardcoded `#ff5e00` color** — This color is from no established palette and violates the project's own conventions.

---

*Audit based on complete source review: `index.astro`, `global.css`, `TerminalDemo.tsx`, `TerminalBlock.astro`, `TrustBlock.astro`, `InstallCommand.astro`, `FeatureBlock.astro`, `ComparisonTable.astro`, `PullQuote.astro`, `Step.astro`, `Button.astro`, `Callout.astro`, `Nav.astro`, `Footer.astro`, `EmailCapture.tsx`, `TeamTierBadge.astro`, `BaseLayout.astro`, `CLAUDE.md`.*
