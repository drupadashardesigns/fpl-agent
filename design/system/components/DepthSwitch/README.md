# DepthSwitch

How the reader picks depth on one story: Headline, The read, Data room.

- Three equal options in a `surface-sunken` track (`radius-md`, padding `space-1`). The active option is `ink` with white text in `label-strong`; inactive options are transparent with `ink-subtle` text in `label`.
- Options are real buttons with `aria-pressed`; the group has `aria-label="How deep"`.
- Choosing a deeper option opens that layer in place, above the switch, and keeps the shallower layers visible. The choice is remembered per story for that edition.
- A story with no data room shows two options, not a disabled third.
- 40px options inside a 48px track, at the bottom of the card.
