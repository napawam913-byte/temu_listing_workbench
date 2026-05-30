export async function exportProducts({ productRepository, sheetExporter }) {
  const products = await productRepository.list();
  const exportableProducts = products.filter((product) => product.status !== "failed");
  return await sheetExporter.export(exportableProducts);
}
