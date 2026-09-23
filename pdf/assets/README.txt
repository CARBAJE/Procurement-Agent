ASSETS DIRECTORY
================

Place static assets here that are referenced from metadata.yaml
or directly embedded in the documentation.

LOGO (optional)
  File:    logo.png  (or logo.pdf)
  Size:    At least 500 x 500 px, transparent background recommended
  Usage:   Uncomment `titlepage-logo: "assets/logo.png"` in metadata.yaml

COVER BACKGROUND (optional)
  File:    cover-background.pdf  (or .png)
  Usage:   Add `titlepage-background: "assets/cover-background.pdf"` to metadata.yaml
           This places a full-page image behind the title page text.
           Ensure the image is dark enough that white text remains readable,
           or change titlepage-text-color to a suitable dark colour.

PAGE BACKGROUND (optional)
  File:    page-background.pdf  (or .png)
  Usage:   Add `page-background: "assets/page-background.pdf"` to metadata.yaml
           Add `page-background-opacity: 0.05` for a subtle watermark effect.

IMAGES referenced from documentation/
  Any image file referenced with a relative path from the documentation/ files
  must also be placed here (or in project_docs/documentation/).
  Pandoc searches the resource-path directories listed in defaults.yaml.
