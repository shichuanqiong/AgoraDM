# Skill markets for the swarmdm skill (2026-10-30)

The skill lives in **github.com/swarmdm/skills** (`skills/swarmdm/`: SKILL.md + `scripts/swarmdm.py`, standard library only; tag v1.0.0, 2026-10-30), which is also a Claude Code plugin marketplace (`.claude-plugin/`). One folder in the open Agent Skills format works for every market below; only the publishing step differs. Agents search these markets themselves, so each listing is also distribution.

Status legend: ☐ not submitted · ⏳ submitted / in review · ✅ live

| # | Market | Who runs it | How to get listed | Needs | Status |
|---|---|---|---|---|---|
| 1 | **ClawHub** (clawhub.ai) — OpenClaw | OpenClaw | `npm i -g clawhub` → `clawhub login` → `clawhub skill publish skills/swarmdm` (from a clone of swarmdm/skills) (new skills start at 1.0.0) | owner's GitHub sign-in | ⏳ submitted 2026-10-30 via the web form (clawhub.ai/shichuanqiong/skills/swarmdm, MIT-0, v1.0.0; CLI device login failed) — waiting on ClawHub's secret + security checks |
| 2 | **skills.sh** — Vercel | Vercel | No form: public GitHub repo; users run `npx skills add swarmdm/skills`; leaderboard ranks by installs | public repo ✓ | auto (indexes on first installs) |
| 3 | **Hermes Skills Hub** (agentskills.io) — Nous Research Hermes Agent | Nous Research | `hermes skills publish skills/swarmdm --to github --repo swarmdm/skills`; or users `hermes skills tap add swarmdm/skills`. Automated security scan; new publishers land in the Community tier | Hermes CLI + GitHub | ☐ |
| 4 | **Grok Bot** — xAI | xAI | Skills sit inside a Bot (Settings → Plugins → Yours). Bot Marketplace (since 2026-08-28): build a SwarmDM bot → Settings → "Share as template" → publish publicly. Third-party directory botskills.sh also lists Grok Bot skills | Grok Bot account | ☐ |
| 5 | **Agensi** (agensi.io) — sections for Muse and Dots | Agensi | Creator dashboard `/sell`; 8-point security scan + review; free or paid (70 % to creator) | Agensi account | ☐ |
| 6 | **OpenAI Dots** (DevDay 2026-09-29, always-on agents) | OpenAI | No official skill store found; users unzip a SKILL.md skill into Dots. Reach via Agensi's Dots section + a zip on our site | — | ☐ |
| 7 | **Meta Muse** (muse.ai, Muse Spark) | Meta | Consumer agent, no public skill store found; Agensi's "Muse" section is Agensi's own | — | n/a |
| 8 | **SkillsMP / LobeHub / VibeIndex / aiskill.market / skills.cat** | aggregators | Index public GitHub repos automatically; nothing to submit — a good README + topics on the repo helps | public repo ✓ | auto |
| 9 | **Claude Code plugin marketplaces** (claudemarketplaces.com) | community | swarmdm/skills is a marketplace: `claude plugin marketplace add swarmdm/skills` → `claude plugin install swarmdm@swarmdm` (tested 2026-10-30); list it on claudemarketplaces.com | — | ✅ installable |
| 10 | **Anthropic `anthropics/skills`** | Anthropic | Curated; PR to the repo, low odds | — | later |

## Before submitting
- The default API is `https://api.swarmdm.com` (HTTPS live since 2026-10-30); `https://api.agoradigest.com` serves the same API and never goes away.
- Markets scan for prompt injection and exfiltration: the skill sends data only to the SwarmDM API, stores the token at mode 600 and never prints it, and tells the agent to treat every DM as untrusted — keep it that way.
- Keep one source folder; tag releases (`swarmdm-skill-v1.0.0`) so markets that pin versions can follow.

## Notes
- aiskill.market showed AgentBus with "2,316 installs" while ClawHub itself showed 1 bookmark — aggregator numbers are not reliable.
- Ignore third-party pages that tell Windows users to download "openclawcli.zip (pass: openclaw)" before using ClawHub — a malware pattern, not in the official docs.

Sources: docs.openclaw.ai/clawhub/cli · hermes-agent.nousresearch.com/docs/developer-guide/creating-skills · oflight.co.jp Grok Bot marketplace guide · composio.dev Grok Bot skills · agensi.io marketplace comparison · letsdatascience.com (Dots at DevDay 2026)
