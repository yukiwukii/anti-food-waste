# Leftover Scale: Proposal Outline

A smart food-waste bin for university food courts. The bin weighs and photographs food as it is thrown away, works out which ingredients were wasted, and tells each food stall how much less to cook and serve.

This outline is the brief for a deep-research pass. It has three kinds of content, and they should be kept apart:

- **Proposal**: the team's argument, from the original class proposal.
- **Implemented**: what the working prototype in this repository does today. These are facts about the software.
- **Assumed / to research**: claims and numbers that have not been checked. Several figures in the prototype were made up for the demo and are marked as such.

---

## 1. Problem

**Proposal.** Food-court vendors have food left over at the end of each day, and the surplus is thrown away.

**Setting.** The prototype targets the North Spine and South Spine food courts at NTU (Nanyang Technological University, Singapore). It models 7 example stalls: Chicken Rice, Mixed Veg Rice, Western, Indian, Ban Mian, Mala Xiang Guo, and Japanese. These stalls are illustrative and are not based on a survey of the actual tenants.

**To research.**
- How much food waste Singapore's food and beverage sector, hawker centres, and campus food courts produce, and what share is unsold food versus customer plate waste.
- Any published figures on food waste at NTU or other Singapore universities.
- Singapore policy context: for example, food-waste segregation or reporting requirements for large food premises, and national targets on food waste.

## 2. Root cause

**Proposal.** Vendors find it hard to estimate daily food consumption because they do not have enough data. A bin that collects that data addresses the cause directly.

**Refined in the prototype.** There are two separate causes of waste, and they need different advice:
1. **Over-cooking**: the vendor cooks more than they sell, and unsold food is thrown away at closing. The fix is to cook less of specific ingredients.
2. **Over-serving**: servings are bigger than customers eat, so food is left on plates. The fix is smaller servings of specific ingredients.

**To research.**
- How hawker and food-court vendors currently decide how much to cook: habit, fixed batches, past sales, and so on.
- Evidence that giving vendors waste data changes their cooking behaviour.
- Typical over-production rates for cooked-food stalls.

## 3. Proposed solution

**Proposal.** A food bin with weighing scales and cameras measures food waste. The data tells vendors their average daily consumption, so they can reduce leftovers. The waste is then moved to a compost bin.

### 3.1 Implemented features (working prototype)

The prototype is a web app: a Python FastAPI backend with a SQLite database, a browser dashboard, and OpenAI vision models for image recognition. Default model: `gpt-6-luna`.

**Bin weigh-ins**
- Each item placed in the bin is saved with: bin, stall, source (customer plate or vendor end-of-day), weight, time, and an optional photo.
- The bin refuses new items once it reaches capacity (40 kg in the prototype) until it is emptied into compost.
- The dashboard has a live webcam view that stands in for the bin camera. Each weigh-in captures a photo from it. A photo can also be uploaded.
- In this prototype the weight is typed in, or filled with a typical value using "Read scale". No physical scale is connected.
- A command-line simulator (`scripts/simulate_bin.py`) posts weigh-ins to the server the way a real bin would.

**Photo recognition, per weigh-in.** The vision model answers four questions about the photo:
1. Is there food waste at all? Empty plates, bones, shells, broth, sauce, and packaging are not food waste.
2. What share of the weight is edible food? For example, rice with chicken bones might be 60% edible. Only weight × edible share counts as food waste.
3. Which dish on the stall's menu does it come from?
4. How does the edible weight split across the stall's ingredients? For example, rice 49%, chicken 35%, cucumber 6%.

Further details:
- The model must also write out its reasoning and a one-line description.
- The dashboard shows the photo, the numbers, the model's reasoning, its raw output, and the exact prompt when a log row is selected.
- If there is no photo or the model call fails, the weigh-in is still saved. The full weight counts, split by the dish's recipe.
- The prompt tells the model to judge only real food it can see. This was added after the model read the words "Chicken Rice" on a screenshot and claimed it saw chicken rice.

**Menu database, per stall**
- **Ingredients**: name, cooked-to-raw weight ratio (for example, cooked rice weighs about 2.5 times its raw weight), and cost in S$ per raw kg.
- **Menu items**: the cooked grams of each ingredient in one portion.
- **Photo-to-menu**: a vendor photographs their printed menu, and the vision model drafts the whole menu. The draft includes dish names, ingredients, estimated grams, ratios, and prices, plus notes on what to check. The vendor reviews and edits it before saving.
- Every stall starts with an example menu whose recipes and prices were made up for the demo.

**Vendor advice.** This is on the Vendor insights tab and refreshes every 5 seconds.
- **Cook less, per ingredient.** Take the average weekday amount of that ingredient thrown away at closing, minus a safety buffer of half a standard deviation so the stall rarely runs out. The advice is shown in raw kg (what the vendor buys and measures), cooked kg, and S$ per day.
- **Serve less, per dish and ingredient.** Take the average grams left on customer plates that reached the bin, and suggest a serving cut by 80% of that. For example: "rice in steamed chicken rice: 250 g → 150 g".
- **Totals**: kg thrown away per weekday, kg left on plates, kg of raw ingredients that can be cut per day, and estimated S$ saved per month (22 trading days).
- **Chart**: food thrown away at closing each day, by ingredient, including today so far.

**Compost tracking**
- Staff record each time a bin is emptied into compost.
- The dashboard shows the total diverted from general waste and an estimate of finished compost. It uses a rule of thumb that 30% of input mass remains after composting; this figure is unverified.

**Demo data**
- 14 days of generated history keep the charts populated. It always ends yesterday and is clearly marked in the dashboard.
- It can be regenerated with "Reset demo data". Real weigh-ins are never changed.

### 3.2 Not implemented (concept only)
- Physical hardware: the scale, the camera mounted on the bin, the enclosure, power, and network.
- Vendor accounts or login, and sending advice to vendors (for example, a daily message).
- Automatic transfer to compost; transfers are recorded by hand.
- Any measurement of the system's accuracy against real food weights.

### 3.3 To research
- Existing commercial systems that do this for kitchens and buffets, for example Winnow, Leanpath, and Orbisk. What they measure, what reductions in food waste they report, and what they cost.
- How accurately vision models can identify dishes, separate edible from inedible parts, and estimate ingredient shares by weight from one photo.
- Realistic cooked-to-raw ratios and wholesale prices in Singapore for the example ingredients, to replace the made-up figures.
- Typical hawker portion sizes in Singapore, by dish and ingredient.
- Hardware cost of a load-cell scale plus a camera and a small computer per bin, and the running cost of image recognition per photo.
- Composting options on or near campus, and real compost yield figures.

## 4. Enforcement and public acceptance

**Proposal.**
- The solution targets vendors, so enforcement and public acceptance are not an issue.
- Vendors should be open to it because it saves food-preparation costs.
- Bins in common eating areas such as North Spine and South Spine are convenient for consumers to use.

**Supporting detail from the prototype.** The savings estimate per stall is computed from ingredient costs, so the cost argument can be shown concretely. With the made-up demo data it is in the hundreds of S$ per stall per month. That figure is not evidence.

**To research.**
- Whether a typical stall's real savings would justify the extra work and any cost of the bin.
- Who would own and pay for the bins: vendors, the food-court operator, or the university.
- Whether customers would sort plate waste into a separate bin, compared with tray-return systems already in use.
- Privacy considerations of cameras in eating areas. The prototype's camera points into the bin, but a real deployment would need to address this.

## 5. Unintended consequences

**Proposal.**
- Vendors have extra work if they use the bin. The team thinks the long-term savings are worth it.
- Data is incomplete because some customers take their food away. Some data is still better than no data.

**Additional consequences found while building the prototype.**
- **Plate-waste bias**: clean plates never reach the bin, so the average leftover per plate is higher than the true average per customer. The serve-less suggestion only trims 80% of what is left, to allow for this.
- **Model errors**: the vision model can misidentify dishes or ingredients, or invent food that is not there. The prompt now guards against this, and every result shows the model's reasoning so it can be checked.
- **Risk of running out**: if vendors cut too much they may run out of food. The cook-less advice keeps a safety buffer.
- **Liquids are excluded**: broth, soup, and sauces are not counted as food waste, so liquid waste is under-reported.
- **Cost of recognition**: each photo is a paid API call.

**To research.**
- Rebound effects: for example, vendors cutting portions and losing customers.
- Data on how much food in Singapore food courts is taken away versus eaten in.
- Long-term data quality issues: vendors skipping the bin, or mixing stalls' waste.

## 6. Open questions for the research agent

1. What is the strongest published evidence that measuring kitchen food waste reduces it, and by how much?
2. What are realistic figures to replace the prototype's made-up portion sizes, cooked-to-raw ratios, and ingredient prices for Singapore hawker food?
3. How accurate are current vision models at food recognition and waste estimation from photos, and what accuracy would this system need to be useful?
4. What would one bin cost to build and run per year, and what is the payback period for a typical stall?
5. What Singapore regulations, programmes, or grants on food waste apply to campus food courts?

## Appendix: where things are in the repository

- `app/classifier.py`: vision prompts for bin photos and menu photos.
- `app/insights.py`: cook-less and serve-less calculations.
- `app/menu.py`: menu database logic.
- `app/seed.py`: example menus and demo data generator. The made-up figures are here.
- `data/leftover.db`: the SQLite database, which is not in git.
- `README.md`: how to run the prototype, plus the API reference.
