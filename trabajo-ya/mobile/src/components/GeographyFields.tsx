import React, { useEffect, useRef, useState } from 'react';
import { Pressable, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import type { GeoCandidate, SearchProposal } from '../types';
import { Button, Field } from './ui';
import { useTheme } from '../theme/theme';
import { locationQueryKey, radiusChoices, radiusLabel, validGeoCandidate } from '../state/geography';

export type ResolveLocation = (location: { city: string; province: string; country: string }) => Promise<{ locations: GeoCandidate[] }>;
interface Props { proposal: SearchProposal; onChange: (patch: Partial<SearchProposal>) => void; onResolve: ResolveLocation; busy: boolean; demo: boolean; showCity?: boolean }

export default function GeographyFields({ proposal, onChange, onResolve, busy, demo, showCity = true }: Props) {
  const { colors } = useTheme();
  const [locations, setLocations] = useState<GeoCandidate[]>([]);
  const [loading, setLoading] = useState(false);
  const [feedback, setFeedback] = useState('');
  const [customRadius, setCustomRadius] = useState(proposal.radius_km ? String(proposal.radius_km) : '');
  const [custom, setCustom] = useState(!radiusChoices.includes((proposal.radius_km ?? 0) as typeof radiusChoices[number]));
  const revision = useRef(0);
  const active = useRef(true);
  const queryKey = locationQueryKey(proposal);
  const latestQuery = useRef(queryKey);
  latestQuery.current = queryKey;

  useEffect(() => { active.current = true; return () => { active.current = false; revision.current++; }; }, []);
  useEffect(() => { revision.current++; setLocations([]); setFeedback(''); setLoading(false); }, [queryKey]);

  const changeLocation = (patch: Partial<SearchProposal>) => {
    revision.current++;
    onChange({ ...patch, location_id: null });
    setLocations([]); setFeedback(''); setLoading(false);
  };
  const resolve = async () => {
    if (!proposal.city.trim() || !(proposal.country ?? 'Argentina').trim()) { setFeedback('Indicá la localidad y el país antes de comprobar la ubicación.'); return; }
    const requestRevision = ++revision.current;
    const requestedKey = queryKey;
    setLoading(true); setFeedback(''); onChange({ location_id: null });
    try {
      const response = await onResolve({ city: proposal.city.trim(), province: (proposal.province || '').trim(), country: (proposal.country ?? 'Argentina').trim() });
      if (!active.current || requestRevision !== revision.current || requestedKey !== latestQuery.current) return;
      const candidates = response.locations.filter(validGeoCandidate);
      setLocations(candidates);
      if (candidates.length === 1) onChange({ location_id: candidates[0].id });
      if (!candidates.length) setFeedback('No se pudo resolver esta localidad. Revisá el nombre, la provincia y el país. No se asignaron coordenadas.');
    } catch (error) {
      if (active.current && requestRevision === revision.current) setFeedback(error instanceof Error ? error.message : 'No pudimos comprobar la ubicación. Intentá nuevamente.');
    } finally {
      if (active.current && requestRevision === revision.current) setLoading(false);
    }
  };

  const selected = locations.find(candidate => candidate.id === proposal.location_id);
  return <View style={{ gap: 14 }}>
    {showCity ? <Field label="Localidad *" value={proposal.city} onChangeText={city => changeLocation({ city })} placeholder="Ej. Rincón de los Sauces" editable={!busy} /> : null}
    <Field label="Provincia / estado" value={proposal.province || ''} onChangeText={province => changeLocation({ province })} placeholder="Ej. Neuquén" editable={!busy} />
    <Field label="País *" value={proposal.country ?? 'Argentina'} onChangeText={country => changeLocation({ country })} placeholder="Ej. Argentina" editable={!busy} />
    {demo ? <Text style={{ color: colors.warning, fontSize: 11, lineHeight: 19 }}>Demostración: no consultamos ubicaciones ni asignamos coordenadas reales.</Text> : <>
      <Button label="Comprobar ubicación" icon="location-outline" variant="secondary" onPress={() => void resolve()} disabled={busy || !proposal.city.trim()} loading={loading} />
      {locations.length > 1 ? <Text style={{ color: colors.text, fontSize: 12, lineHeight: 20 }}>Hay más de una coincidencia. Elegí la localidad correcta para evitar buscar en otra zona.</Text> : null}
      {locations.map(candidate => <Pressable key={candidate.id} accessibilityRole="radio" accessibilityLabel={candidate.label} accessibilityState={{ selected: candidate.id === proposal.location_id }} disabled={busy || loading} onPress={() => onChange({ location_id: candidate.id })} style={{ borderWidth: 1, borderColor: candidate.id === proposal.location_id ? colors.primary : colors.border, backgroundColor: candidate.id === proposal.location_id ? colors.primarySoft : colors.bg, borderRadius: 11, padding: 14, gap: 6 }}>
        <View style={{ flexDirection: 'row', gap: 10, alignItems: 'center' }}><Ionicons name={candidate.id === proposal.location_id ? 'radio-button-on' : 'radio-button-off'} size={18} color={colors.primary} /><Text style={{ color: colors.text, fontSize: 12, lineHeight: 20, flex: 1 }}>{candidate.label}</Text></View>
        <Text style={{ color: colors.muted, fontSize: 10, lineHeight: 17 }}>Referencia: {candidate.provider || candidate.source || candidate.coordsSource || 'Servicio de ubicaciones'} · {candidate.latitude.toFixed(4)}, {candidate.longitude.toFixed(4)}</Text>
      </Pressable>)}
      {selected ? <Text style={{ color: colors.primary, fontSize: 11, lineHeight: 19 }}>Ubicación elegida: {selected.label}. Se volverá a validar al guardar.</Text> : <Text style={{ color: colors.muted, fontSize: 11, lineHeight: 19 }}>Comprobá la ubicación y elegí una coincidencia antes de guardar.</Text>}
    </>}
    <Text style={{ color: colors.text, fontSize: 12, fontWeight: '600' }}>Zona de búsqueda</Text>
    <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>{radiusChoices.map(radius => <Pressable key={radius} accessibilityRole="radio" accessibilityState={{ selected: !custom && (proposal.radius_km ?? 0) === radius }} disabled={busy} onPress={() => { setCustom(false); onChange({ radius_km: radius }); }} style={{ paddingHorizontal: 12, paddingVertical: 10, borderWidth: 1, borderRadius: 9, borderColor: !custom && (proposal.radius_km ?? 0) === radius ? colors.primary : colors.border, backgroundColor: !custom && (proposal.radius_km ?? 0) === radius ? colors.primarySoft : colors.bg }}><Text style={{ color: colors.text, fontSize: 11 }}>{radius === 0 ? 'Localidad' : `${radius} km`}</Text></Pressable>)}
      <Pressable accessibilityRole="radio" accessibilityState={{ selected: custom }} disabled={busy} onPress={() => { setCustom(true); setCustomRadius(proposal.radius_km ? String(proposal.radius_km) : ''); }} style={{ paddingHorizontal: 12, paddingVertical: 10, borderWidth: 1, borderRadius: 9, borderColor: custom ? colors.primary : colors.border, backgroundColor: custom ? colors.primarySoft : colors.bg }}><Text style={{ color: colors.text, fontSize: 11 }}>Otro radio</Text></Pressable>
    </View>
    {custom ? <Field label="Radio personalizado (0 a 1000 km)" value={customRadius} onChangeText={value => { setCustomRadius(value); onChange({ radius_km: /^\d+$/.test(value) ? Number(value) : Number.NaN }); }} keyboardType="number-pad" editable={!busy} /> : null}
    <Text style={{ color: colors.muted, fontSize: 11, lineHeight: 19 }}>{radiusLabel(proposal.radius_km)}. La distancia usa referencias geográficas de localidades; no representa kilómetros por ruta ni la dirección exacta del puesto. Las ubicaciones dudosas quedan pendientes de revisión.</Text>
    {feedback ? <Text accessibilityRole="alert" style={{ color: colors.danger, fontSize: 11, lineHeight: 19 }}>{feedback}</Text> : null}
  </View>;
}
