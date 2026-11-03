# AlooSoul Floodlight Day

The look of the AlooSoul FPL agent: a weekly edition you read in under a minute and go deeper on only when you want to. Bright, friendly and above all easy on the eyes.

## Content fundamentals

The app is an editor, not a dashboard. Every screen leads with what to do, then why.

- **Three layers of depth.** Headline (10 words or fewer) and a 2 to 3 sentence paragraph. The read (300 to 600 words). The data room (full analysis, only for the 1 or 2 decisions that matter that week). The reader picks the depth with the depth switch.
- **Plain, direct language.** Short sentences, sentence case everywhere, no all-caps labels, no em dashes.
- **Facts and projections stay apart.** "Van Hecke scored 15" is a fact. "Tavernier projects 5.1" is a projection and says so.
- **Every number has context.** "+14.4 pts over 6 GWs", never "+14.4".
- **Never "will".** Projects, likely, the model expects.

Examples: "Rogers is in 90% of top 10k teams" (headline). "Save it for the festive triple-header" (headline). "Try it in the planner" (button: says exactly what happens).

## Visual foundations

**Colour.** Two identity colours: `orange` (energy, decisions, the one thing to press) and `ink` navy (weight, the call, navigation). Everything readable sits on `ground` or `surface`. Tints label the kind of story: `orange-tint` for decisions and price rises, `green-tint` for looking back, `blue-tint` for fixtures and data, `red-tint` only for falls and injuries on players you own. Text on orange is always `on-orange`, never white.

**Type.** Two faces chosen for legibility. `display` (Plus Jakarta Sans) for headlines, section titles, numbers and buttons: normal width, open counters, friendly. `text` (Atkinson Hyperlegible Next) for everything you read, designed by the Braille Institute so 1, l and I, or 0 and O, are never confused. Body is 16px on 26px. Nothing below 14px. Numbers in tables use tabular figures.

**Space and shape.** A 20px screen gutter, 28px between sections, 16px inside cards. Generous radii: 14px for buttons and rows, 18px for cards, 20px for the call card and nav, pills fully round. No borders on cards; separation comes from `surface` on `ground`. No shadows, no gradients.

**Layout.** Phone first at 390px. Order of the edition screen: orange header (edition headline and four stats), navy call card overlapping it slightly, headlines, alerts, bottom nav.

## Interaction

- **Depth switch.** Every headline card ends with a three-option switch: Headline, The read, Data room. Choosing a deeper option opens it in place, above the switch. The choice is per story.
- **Primary action** per screen is one orange button. Secondary actions are outlined.
- **Touch targets** are at least 44px tall; the depth switch options are 40px inside a 48px track.
- **Focus** is a 2px `focus` ring with a 2px offset on every control.

## Iconography

None yet. Arrows are the text character →. Small status dots use the tag's colour. Add an outline icon set before adding any icon.

## Components

Button, Chip, StatTile, TransferRow, DepthSwitch, HeadlineCard, Alert, BottomNav. Each has a preview and guidelines.
