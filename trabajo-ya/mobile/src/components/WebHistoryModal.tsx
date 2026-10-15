import React, { useEffect, useRef, useState } from 'react';
import { Linking, Modal, ScrollView, StyleSheet, Text, View } from 'react-native';
import 'react-native-url-polyfill/auto';
import type { ResearchEvent } from '../types';
import { useTheme } from '../theme/theme';
import { Badge, Button, Card, EmptyState, IconButton } from './ui';
import { publicOfferUrl } from '../services/publicUrl';

interface Props { history: { name: string; events: ResearchEvent[] } | null; onClose: () => void }
const statusLabels: Record<ResearchEvent['status'], string> = { started: 'Iniciada, sin resultado confirmado', succeeded: 'Completada', failed: 'Con error', blocked: 'Bloqueada' };
const kindLabels: Record<string, string> = { tavily_query: 'Consulta a Tavily', public_page: 'Lectura de página pública', web_search: 'Consulta web', search: 'Consulta web', page_fetch: 'Lectura de página', fetch: 'Lectura de página', page_extract: 'Lectura de página', extract: 'Lectura de página', ai_analysis: 'Análisis de ofertas', analysis: 'Análisis de ofertas', location_resolve: 'Consulta de ubicación', geocode: 'Consulta de ubicación', source_verification: 'Verificación de fuente' };
function dateLabel(value: string | null | undefined): string { if (!value) return 'No registrada'; const date = new Date(value); return Number.isNaN(date.getTime()) ? 'Fecha no disponible' : date.toLocaleString('es-AR'); }

export default function WebHistoryModal({ history, onClose }: Props) {
  const { colors } = useTheme();
  const [feedback, setFeedback] = useState('');
  const [opening, setOpening] = useState(false);
  const revision = useRef(0);
  const openingLock = useRef(false);
  useEffect(() => { revision.current++; openingLock.current = false; setFeedback(''); setOpening(false); return () => { revision.current++; }; }, [history]);
  const open = async (value: string) => {
    if (openingLock.current) return;
    const url = publicOfferUrl(value);
    if (!url) { setFeedback('Este registro no tiene un enlace público seguro para abrir.'); return; }
    const currentRevision = revision.current;
    openingLock.current = true; setOpening(true); setFeedback('');
    try { await Linking.openURL(url); }
    catch { if (revision.current === currentRevision) setFeedback('No pudimos abrir el enlace. Revisá tu conexión y volvé a intentarlo.'); }
    finally { if (revision.current === currentRevision) { openingLock.current = false; setOpening(false); } }
  };
  return <Modal visible={!!history} transparent animationType="fade" onRequestClose={onClose}><View style={styles.overlay}><View style={[styles.modal, { backgroundColor: colors.surface, borderColor: colors.border }]}>
    <View style={styles.header}><View style={{ flex: 1, gap: 7 }}><Text style={{ color: colors.muted, fontSize: 9, letterSpacing: 1.4 }}>INVESTIGACIÓN REGISTRADA</Text><Text style={{ color: colors.text, fontSize: 23, fontWeight: '600' }}>Consultas web</Text><Text style={[styles.detail, { color: colors.muted }]}>{history?.name}</Text></View><IconButton icon="close-outline" accessibilityLabel="Cerrar consultas web" onPress={onClose} /></View>
    <ScrollView contentContainerStyle={styles.content}>
      <Text style={[styles.body, { color: colors.muted }]}>Cada registro corresponde a una operación del servidor. Una consulta iniciada no confirma una respuesta. Una página consultada tampoco confirma una vacante vigente ni un envío de correo.</Text>
      {!history?.events.length ? <EmptyState icon="globe-outline" title="Sin consultas registradas" description="Todavía no hay registros web para esta búsqueda. Ejecutala y revisá también el historial de ejecuciones si el servidor informa un error." /> : history.events.map(event => <Card key={event.id} style={{ gap: 10, padding: 17 }}>
        <Text style={{ color: colors.text, fontSize: 14, fontWeight: '600' }}>{kindLabels[event.kind] || event.kind || 'Operación web'}</Text>
        <Badge label={statusLabels[event.status] || 'Estado no disponible'} tone={event.status === 'succeeded' ? 'success' : event.status === 'failed' ? 'danger' : 'warning'} />
        <Text style={[styles.detail, { color: colors.muted }]}>Proveedor: {event.provider || 'No informado'}</Text>
        <Text style={[styles.detail, { color: colors.muted }]}>Inicio: {dateLabel(event.started_at)}</Text>
        {event.finished_at ? <Text style={[styles.detail, { color: colors.muted }]}>Finalización: {dateLabel(event.finished_at)}</Text> : null}
        {event.query ? <Text selectable style={[styles.body, { color: colors.text }]}>Consulta: {event.query}</Text> : null}
        {event.url ? <Text selectable style={[styles.detail, { color: colors.text }]}>Página: {event.url}</Text> : null}
        {publicOfferUrl(event.url) ? <Button label="Abrir página consultada" icon="open-outline" variant="ghost" onPress={() => void open(event.url!)} disabled={opening} /> : null}
        {event.source_hosts?.length ? <Text selectable style={[styles.detail, { color: colors.muted }]}>Sitios: {event.source_hosts.join(' · ')}</Text> : null}
        {typeof event.http_status === 'number' ? <Text style={[styles.detail, { color: colors.muted }]}>Respuesta HTTP: {event.http_status}</Text> : null}
        {event.provider_request_id ? <Text selectable style={[styles.detail, { color: colors.muted }]}>Identificador del proveedor: {event.provider_request_id}</Text> : null}
        {typeof event.credits === 'number' && Number.isFinite(event.credits) ? <Text style={[styles.detail, { color: colors.muted }]}>Créditos informados por el proveedor: {event.credits}</Text> : null}
        {event.result_urls?.length ? <View style={{ gap: 7 }}><Text style={[styles.detail, { color: colors.text }]}>Enlaces devueltos: {event.result_urls.length}</Text>{event.result_urls.map((url, index) => <View key={`${index}-${url}`} style={{ gap: 4 }}><Text selectable style={[styles.detail, { color: colors.muted }]}>{url}</Text>{publicOfferUrl(url) ? <Button label={`Abrir resultado ${index + 1}`} icon="open-outline" variant="ghost" onPress={() => void open(url)} disabled={opening} /> : null}</View>)}</View> : null}
        {event.error ? <Text selectable accessibilityRole="alert" style={[styles.body, { color: colors.danger }]}>{event.error}</Text> : null}
        {event.recorded_at ? <Text style={[styles.detail, { color: colors.muted }]}>Registrada: {dateLabel(event.recorded_at)}</Text> : null}
      </Card>)}
      {feedback ? <Text accessibilityRole="alert" style={[styles.body, { color: colors.danger }]}>{feedback}</Text> : null}
      <Button label="Cerrar" variant="secondary" onPress={onClose} />
    </ScrollView>
  </View></View></Modal>;
}

const styles = StyleSheet.create({ overlay: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(8, 19, 32, .65)', padding: 18 }, modal: { width: '100%', maxWidth: 640, maxHeight: '90%', borderRadius: 22, borderWidth: 1, overflow: 'hidden' }, header: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 22, paddingTop: 22, paddingBottom: 16 }, content: { paddingHorizontal: 22, paddingBottom: 22, gap: 14 }, body: { fontSize: 12, lineHeight: 21 }, detail: { fontSize: 11, lineHeight: 18 } });
