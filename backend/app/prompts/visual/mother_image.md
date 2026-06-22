Create one single {{ layoutKey }} ecommerce mother image.

This mother image contains {{ expectedCount }} independent square listing-image panels.

Grid rules:
{{ gridRules }}

Global product consistency:
1. Use analyzed reference image facts, reference image labels/titles, and SKU/component binding facts as binding product references.
2. Treat all reference images as equal product references.
3. Preserve product visual identity for every SKU/component with supplied visual facts: silhouette, geometry, body shape, proportions, color, material attributes, surface finish, tactile texture, wrinkles/folds, rigidity/flexibility, construction, quantity, structure, component relationship, edge details, and printed pattern.
4. Do not swap products between reference images, merge different products into one generic item, or replace the selected product/SKU with a generic category item.
5. Visual appearance weight rule: attached reference images have 100% weight for product appearance and visual identity.
6. Product identity lock: never change material attributes, surface finish, tactile texture, wrinkles/folds, rigidity/flexibility, body shape, silhouette, proportions, construction, color arrangement, component count, or component relationship.
7. Object-type lock: never transform the selected product into another object type, package, container, functional form, or generic category substitute unless that form is visibly present in the reference image.
8. Copy truth lock: on-image copy must not name any shape, material, texture, surface finish, construction, component, or function that is not visibly supported by the reference image.
9. Material texture drift lock: {{ materialTextureDriftRule }}
10. Keep all panels visually coherent as one commercial listing batch.

Product facts to preserve:
{{ productJson }}

SKU/component binding facts:
{{ skuBindingJson }}

Combo SKU composition facts:
{{ skuComboJson }}

Reference image to SKU/source product title bindings:
{{ skuReferenceJson }}

Global safety:
No brand logo, platform logo, watermark, QR code, price, discount, rating, certification badge, medical claim, absolute claim, stock claim, shipping-time claim, or platform UI.

Panel instructions:
{{ panelInstructions }}

Final output:
One complete {{ layoutKey }} mother image only.
