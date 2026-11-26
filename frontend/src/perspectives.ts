/**
 * The two ways HEATBEAT looks at every data center, used the same in the ranking, the site panel and
 * the planner:
 *   cooling     the heat is cooled away; which heat rejection saves the most money (NPV)
 *   heat waste  the heat is a by-product to use; which design reuses the most of it and still pays off
 */
export type Perspective = 'cooling' | 'heat';

export const PERSPECTIVES: Record<Perspective, { label: string; def: string }> = {
  cooling: {
    label: 'Cooling',
    def: 'Most money saved by changing how the heat is cooled away: value over 20 years (NPV) compared with today.',
  },
  heat: {
    label: 'Heat waste',
    def: 'Most server heat put to use instead of cooled away, by a design that pays off (positive NPV for the reuse and the whole project).',
  },
};
