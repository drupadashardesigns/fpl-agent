# HeadlineCard

One story in the weekly edition, holding all three layers.

- Order: tag (Chip), headline (`headline`, 10 words or fewer), paragraph (`body`, `ink-muted`, 2 or 3 sentences), the opened layers, then the DepthSwitch.
- The read opens under the paragraph after a 1px `line` rule, in `body` and `ink`. The data room opens as a `ground` inset panel with its chart and a link to the full analysis.
- `surface` card on `ground`, `radius-lg`, padding 18px, inner gap 10px, cards `space-4` apart. No border, no shadow.
- The consumer provides the tag kind, headline, paragraph, read text and an optional data room id.
