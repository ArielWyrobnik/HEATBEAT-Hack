/**
 * Shape of one data center pin.
 * Drop an array of these into `public/datacenters.json` and the map picks them up.
 * Only id, name, lat, lng are required – everything else is optional and shown if present.
 */
export interface DataCenter {
  id: string;
  name: string;
  lat: number;
  lng: number;
  operator?: string;
  city?: string;
  country?: string;
  /** Power capacity in MW */
  capacityMW?: number;
  /** Power Usage Effectiveness, e.g. 1.4 */
  pue?: number;
  /** Free-form extra fields from the data pipeline */
  [key: string]: unknown;
}
