# TRUTHBOUND IV — Hackathon Strategy

## The Meta-Principle
**Target underserved tracks.** Judges see 60-100 projects. The winner is almost never the best-executed generic idea — it's the one that uses the sponsor's tech in a way the sponsor built it for but rarely sees.

---

## Why You Lose Hackathons (Brutal Assessment)
1. **Generic idea** — "AI agent that monitors X." Every LLM suggests this. Judges see 40 of them.
2. **Sponsor tech as decoration** — "We use Chainlink for price data" when you could remove Chainlink and nothing breaks. Judges notice.
3. **Too much scope** — 80% complete across 5 features vs 100% complete on 1 feature. Judges only remember the demo.
4. **Poor demo moment** — no single WOW in the 3-minute presentation. Judges move on.
5. **Missing the judging criteria** — building for technical elegance when criteria weight real-world impact 40%.

---

## Why You Win

### The 3-Minute Rule
Judges are tired. By project 50, their default answer is "nice." To win, you need ONE moment where they lean forward. Design backward from that moment:
1. What is the single most surprising thing your project can show?
2. Build everything else to lead up to that moment.
3. Cut anything that doesn't support the moment.

### The "Built for This" Rule
The Chainlink team built Functions because they wanted non-financial use cases. The FVM team built Filecoin EVM because they wanted programmable storage. The Seeker team built the hardware seed vault because they wanted hardware-anchored trust. **Demo the features they built and no one uses.** You signal: "I did my homework."

### The Narrative Rule
Technical quality is a filter, not a selector. After filtering for "does it work," judges pick based on narrative:
- Problem: specific, verifiable, not hypothetical
- Solution: only possible with this sponsor's tech (not swappable)
- Demo: real data, not mock data. Historical replays beat simulated futures.
- Vision: one sentence that makes a judge think "this could be real in 3 years"

---

## TRUTHBOUND IV's Winning Narrative

**One-line pitch:** "SENTINEL makes AI reasoning auditable on-chain — because trust without proof is just marketing."

**Why it works across events:**
- Chainlink: oracle disagreement is a security signal (non-obvious angle)
- PL Genesis: content-addressed knowledge graph (native to PL's mission)
- Starknet: ZK proofs make AI inference verifiable without revealing inputs
- Seeker: hardware-backed attestations anchor AI claims to physical reality
- ERC-8004: accountability middleware for AI agent permission delegation

**The key:** same core concept (AI + on-chain truth), different sponsor tech entry point. Build once, rebrand 5 times.

---

## What Every LLM (Including Claude) Will Suggest
These are the ideas that show up in every hackathon. Avoid all of them:
- "AI-powered smart contract auditor"
- "Decentralized AI training / federated learning"
- "Privacy-preserving data marketplace"
- "AI chatbot with on-chain memory"
- "Sentiment analysis trading bot"
- "Cross-chain bridge with AI routing"
- "NFT generator with AI"
- "DeFi yield optimizer with AI signals"
- "Crypto portfolio tracker with AI analysis"
- "Telegram bot + Web3" (confirmed oversaturated, research-backed)

If you can describe your project in one of these templates: start over.

## Research-Confirmed: What Wins Per Ecosystem

**Chainlink:** Multi-service (CRE + Functions + Automation + CCIP). Non-DeFi CAN win (Block Magic 2024 grand prize was an educational game). Judge Scott Dykstra co-founded Space and Time — integrate it.

**Protocol Labs:** "Improve the infrastructure, don't just use it." Open Data track judges want the "this could be huge" moment AND clean UX for researchers/scientists. Build FOR researchers, not for crypto users.

**Starknet:** Cairo performance matters — judges are Cairo language engineers. Use Poseidon hashing, benchmark your circuit. The gap between Cairo-native and Solidity-port is immediately obvious to these judges.

**Solana Mobile:** Utility wins over DeFi complexity. Tap (cash app, $30K) and LootGo ($25K) were both daily-use utility apps, not protocol dashboards. Ask: would a non-crypto person open this daily?

**lablab.ai:** Business Value = 30% of score (most underestimate this). Domain-specific agents win over general assistants. Recent winners: supply chain risk, route optimization, logistics — all have clear P&L impact numbers.

## The Narrow Scope Rule (Confirmed)
Research confirmed: "a working mediocre idea beats a half-built genius idea." Judges penalize:
- Projects that promise a "platform" instead of solving one problem
- Scope that requires 2 weeks to build shipped in 48 hours
- Any "future work" section longer than one line

**The fix:** Pick ONE narrow use case. "SENTINEL verifies oracle disagreement events for DeFi lending protocols" beats "SENTINEL is a universal AI truth layer for all information."

---

## Build Strategy

### Phase 0 — Foundation (Day 1, ~15h)
Build shared components that unlock 5 events:
1. `sentinel-core` — AI claim analyzer, REST API, 8h
2. `on-chain-commitment` — 40-line Solidity contract, 3h
3. `react-shell` — wallet connect + score visualization, 4h

These three unlock Chainlink, PL Genesis, Starknet, ERC-8004, StableHacks.

### The Build Order (Why It Matters)
1. Chainlink (Mar 8) — first, uses sentinel-core + Chainlink Functions, 16h new work
2. Starknet (Mar 10) — second, shares sentinel-core, adds Cairo circuit, 20h new work
3. Seeker (Mar 9) — parallel with Starknet, completely different stack, 20h
4. PL Genesis (Mar 16) — the big one, most effort, 34h focused work
5. ERC-8004 (Mar 22) — last, reuses sentinel-core + on-chain-commitment, 20h

---

## Demo Construction Rules
1. Use **real historical data** for replays. Coingecko historical API, Wikipedia facts, real block data.
2. Show **contrast**: honest vs deceptive agent. Before vs after. Manipulated vs verified.
3. **Time your demo to the submission requirements.** Most hackathons want 2-3 minute videos.
4. **Ship the demo video FIRST, then polish code.** Judges see the video. Most don't clone the repo.
5. Write a **single compelling README sentence** first. If you can't write it, the project isn't clear enough.

---

## Submission Checklist (per event)
- [ ] Smart contract deployed on testnet (not localhost)
- [ ] Frontend hosted (Vercel free tier, or GitHub Pages)
- [ ] Demo video: 2-3 minutes, shows the WOW moment, real data
- [ ] GitHub repo: clean README, setup instructions that actually work
- [ ] Submission form filled correctly: tracks selected match your implementation
- [ ] Project uses the sponsor's specific tech in a non-swappable way

---

## Prize Money is Not the Only Signal

In order of long-term value:
1. **PL Genesis Founders Forge** — VC funnel. Worth more than any cash prize.
2. **Chainlink ecosystem grant pipeline** — winning Chainlink hackathons gets you on their radar for ecosystem grants.
3. **Starknet dev grants** — Starkware has ongoing developer grants; hackathon winners get introductions.
4. Cash prizes (direct value but doesn't compound).
5. **Network at judging events** — the people you meet judging are worth more than the prize.

---

## Honest Assessment of TRUTHBOUND IV
**Strengths:** The AI + on-chain truth theme is genuinely differentiated. It's not DeFi. It's not a token. Judges who are tired of DeFi projects will notice it.

**Risks:**
- zkML for Starknet is technically ambitious for a 6-day solo sprint. Scope down the circuit aggressively.
- PL Genesis needs the strongest demo — don't underinvest in the UI.
- "Truth layer" is abstract. Make it concrete with a specific, memorable use case for each event.

**Confidence in winning any single event:** Low-to-medium (hackathons are noisy). Confidence in generating multiple submissions with differentiated, non-generic ideas: High.
