import type { GeoCandidate, JobSearch, SearchProposal } from '../types';

export const radiusChoices = [0, 10, 25, 50, 100, 200, 500] as const;

export function validRadius(value: number | null | undefined): boolean {
  return value === undefined || value === null || (Number.isInteger(value) && value >= 0 && value <= 1000);
}

export function radiusLabel(value: number | null | undefined): string {
  if (value === undefined || value === null) return 'Localidad; sin radio configurado';
  if (!validRadius(value)) return 'Radio pendiente de corregir';
  return value === 0 ? 'Solo la localidad' : `${value} km en línea recta, aproximados`;
}

export function locationQueryKey(proposal: Pick<SearchProposal, 'city' | 'province' | 'country'>): string {
  return JSON.stringify([proposal.city.trim(), (proposal.province || '').trim(), (proposal.country ?? 'Argentina').trim()]);
}

export function validGeoCandidate(candidate: GeoCandidate): boolean {
  return typeof candidate.id === 'string' && !!candidate.id.trim()
    && typeof candidate.city === 'string' && !!candidate.city.trim()
    && typeof candidate.province === 'string' && !!candidate.province.trim()
    && typeof candidate.country === 'string' && !!candidate.country.trim()
    && Number.isFinite(candidate.latitude) && Math.abs(candidate.latitude) <= 90
    && Number.isFinite(candidate.longitude) && Math.abs(candidate.longitude) <= 180;
}

const normalized = (value: string | null | undefined) => (value || '').trim().normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('es');

export function sameSearchConfiguration(search: JobSearch, proposal: SearchProposal): boolean {
  const samePlace = proposal.location_id
    ? search.location?.id === proposal.location_id || search.location_id === proposal.location_id
    : search.cities.includes(proposal.city)
      && normalized(search.province ?? search.location?.province) === normalized(proposal.province)
      && normalized(search.country ?? search.location?.country) === normalized(proposal.country);
  return search.name === proposal.title
    && search.roles.includes(proposal.role) && samePlace
    && (search.radius_km ?? 0) === (proposal.radius_km ?? 0)
    && search.schedule_time.slice(0, 5) === proposal.time && search.timezone === proposal.timezone
    && search.frequency === proposal.frequency
    && [...search.weekdays].sort().join(',') === [...proposal.weekdays].sort().join(',')
    && (!proposal.resume_id || search.preferred_resume_id === proposal.resume_id);
}
