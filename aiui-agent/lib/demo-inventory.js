// DEMO seed for LOCAL mode only (mirrors sample-data/inventory_demo.csv).
// Not company data. Used once, only when no local inventory exists in storage.
export const DEMO_PRODUCTS = [
  { product_id: 'CARE-SENS-AIR-SENSOR', product_name: 'CareSens Air Sensor', stock_qty: 20, unit: 'ea', lot_no: 'DEMO-LOT-A', qr_value: 'CARE-SENS-AIR-SENSOR', barcode: '0880000000001', aliases: ['케어센스 에어 센서', '케어센스 센서', '케어센스', '센서', 'caresens sensor'] },
  { product_id: 'CARE-SENS-AIR-APPLICATOR', product_name: 'CareSens Air Applicator', stock_qty: 10, unit: 'ea', lot_no: 'DEMO-LOT-B', qr_value: 'CARE-SENS-AIR-APPLICATOR', barcode: '0880000000002', aliases: ['케어센스 에어 어플리케이터', '케어센스 어플리케이터', '어플리케이터', 'applicator'] },
  { product_id: 'HICARDI-PATCH', product_name: 'HiCardi Patch', stock_qty: 15, unit: 'ea', lot_no: 'DEMO-LOT-C', qr_value: 'HICARDI-PATCH', barcode: '0880000000003', aliases: ['하이카디 패치', '하이카디', '패치', 'hicardi patch'] },
];
