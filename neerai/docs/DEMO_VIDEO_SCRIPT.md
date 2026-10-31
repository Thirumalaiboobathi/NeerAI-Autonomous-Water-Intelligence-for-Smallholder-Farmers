# Demo video script (target 2:50, limit 3:00)

Setup: `python scripts/demo.py`, browser at 1280x720, language Tamil, Settings > weather = "uncertain rain". Farm "Sample farm - Melur, Madurai".

| Time | Screen | Narration |
|---|---|---|
| 0:00-0:20 | Title, then Dashboard in Tamil | "In Tamil Nadu, farmers irrigate by habit while groundwater falls. Weather apps give forecasts, chatbots give advice. NeerAI gives a decision: what to do with every drop today." |
| 0:20-0:45 | Dashboard: weather card (SIMULATED chip), field cards | "Madurai sample farm, two hectares: paddy, groundnut, ragi. The weather is labelled simulated here - NeerAI never passes demo data off as live. Rain chance is 60%, forecast confidence low." |
| 0:45-1:20 | Click "Run multi-agent assessment" -> timeline | "Seven Strands agents collaborate: context, weather, FAO-56 crop water, budget, decision, Tamil communication. Every tool call is traced. The LLM never computes numbers - tools do." |
| 1:20-1:50 | Water Scarcity page: set paddy priority High | "Demand is 1,161 cubic metres; the farmer has 700. Critical-stage groundnut is funded first, paddy gets 30%, unmet demand is shown. Change a priority and it recalculates instantly." |
| 1:50-2:20 | What-If Simulator: rain 25 mm @ 90%, run; then Heatwave preset | "What if rain comes? Paddy irrigation is deferred and demand drops. What if a heatwave hits? Demand rises and risk fields appear. All inputs are marked hypothetical." |
| 2:20-2:40 | Ask NeerAI: "Explain my water plan in Tamil." -> Why this decision? | "Plain Tamil, voice-ready, with numbers copied from tools. 'Why this decision?' shows weather evidence, assumptions and what would change the advice." |
| 2:40-2:50 | Impact page + architecture diagram | "Impact separates estimated, simulated and measured savings - measured is zero until farmers log meter data. Built with Strands Agents on Amazon Bedrock, Lambda, DynamoDB and CloudFront." |

Do not claim real water savings in the narration.
