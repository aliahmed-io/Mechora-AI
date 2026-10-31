# Asset provenance

## Industrial generator

`public/turbine.png` is an original image created using the built-in image-generation tool. `public/turbine.webp` is its optimized website asset (Pillow, quality 87). The reference screenshot guided the visual composition of the website; it is not shipped as a flattened interface.

Generation prompt:

> Create a photorealistic premium industrial editorial photograph for a website hero. A magnificent large vintage electric generator / turbine assembly, three quarter view with shaft pointing toward lower left, perfectly detailed warm brushed silver steel, dark wine-burgundy painted outer ring, bolts, copper windings and cooling fins. Machine fills right 80 percent of a landscape 3:2 image, tightly cropped on right, with light warm ivory studio background and directional lighting from upper left, deep rich shadows in assembly. Refined luxury automotive advertising photography, authentic engineering, warm desaturated color grading, extreme material detail. No text, no letters, no graphic overlays, no interface. Original photograph style. Output landscape image.

The depicted machine and measurement hotspots are illustrative. They are not photographs of a machine represented in the AI4I data and do not establish a validated link between a component and a model prediction.

## Typography

Instrument Serif, DM Sans, and JetBrains Mono are locally vendored from Google Fonts. Their SIL Open Font License notices are included alongside the files in `public/fonts`. `scripts/vendor_fonts.py` records the download procedure. Application rendering requires no third-party font requests.

## Brand icons

`app/icon.svg` is an original vector Mechora monogram: a cream serif M and brass dot on a burgundy tile. The lettering is drawn as paths and requires no font download. `app/favicon.ico` contains 16, 32, 48, 64, 128, and 256px versions rendered from this SVG. `app/apple-icon.png` is the corresponding 180px home-screen icon. Next.js includes these icons on every page through its file-based metadata convention.

## Dataset

Matzka, S. (2020). *AI4I 2020 Predictive Maintenance Dataset*. UCI Machine Learning Repository. https://doi.org/10.24432/C5HS5C. CC BY 4.0.

The original CSV is preserved. The public inference sample contains the 2,000 test feature rows, without outcome labels or identifiers. Trained probabilities are generated locally; hero probabilities are explicitly illustrative.
