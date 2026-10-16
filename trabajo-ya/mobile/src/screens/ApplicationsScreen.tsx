import React, { useState } from 'react';
import { Modal, Pressable, ScrollView, StyleSheet, Text, TextInput, View, useWindowDimensions } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import type { Application, Resume } from '../types';
import { Badge, Button, Card, Divider, EmptyState, IconButton, ScreenHeader } from '../components/ui';
import { useTheme } from '../theme/theme';

interface Props { applications: Application[]; resumes: Resume[]; busy: boolean; onSend: (id: string) => Promise<void>; demo: boolean; onStopFollowups?: (id: string) => Promise<void> }
const filters: { label: string; key: string }[] = [{ label: 'Todas', key: 'all' }, { label: 'Pendientes', key: 'pending' }, { label: 'Enviadas', key: 'sent' }, { label: 'Respondidas', key: 'responded' }, { label: 'Con error', key: 'error' }];
function stateOf(application: Application): { label: string; tone: 'warning' | 'success' | 'danger' | 'info' } {
  if (application.delivery_uncertain) return { label: 'Revisión necesaria', tone: 'warning' };
  if ((application.status === 'sent' || application.status === 'responded') && (!application.provider_message_id || !application.provider_confirmed_at)) return { label: 'Sin confirmación', tone: 'warning' };
  if (application.status === 'sent') return { label: 'Enviado', tone: 'success' };
  if (application.status === 'responded') return { label: 'Respondido', tone: 'info' };
  if (application.status === 'error') return { label: 'Error', tone: 'danger' };
  if (application.send_attempt_id) return { label: 'En proceso · verificar', tone: 'warning' };
  return { label: 'Pendiente', tone: 'warning' };
}
function formatDate(value: string) { const date = new Date(value); return isNaN(date.getTime()) ? 'Fecha no disponible' : date.toLocaleString('es-AR', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }); }
function deliveryLabel(application: Application) { return application.parent_application_id || (application.delivery_sequence ?? 0) > 0 ? `Reenvío${application.delivery_sequence ? ` ${application.delivery_sequence}` : ''}` : 'Primer envío'; }
function deliveryDate(application: Application) { return application.provider_confirmed_at || application.attempted_at || application.created_at; }
export default function ApplicationsScreen({ applications, resumes, busy, onSend, demo, onStopFollowups }: Props) {
  const { colors } = useTheme();
  const { width } = useWindowDimensions();
  const [filter, setFilter] = useState('all');
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<Application | null>(null);
  const [consent, setConsent] = useState(false);
  const [sendFeedback, setSendFeedback] = useState<{ applicationId: string; message: string } | null>(null);
  const [stoppedRecipients, setStoppedRecipients] = useState<string[]>([]);
  const [stopping, setStopping] = useState(false);
  const [stopFeedback, setStopFeedback] = useState<{ text: string; error: boolean } | null>(null);
  const selectedApplication = applications.find(item => item.id === selected?.id) ?? selected;
  const selectedResume = resumes.find(resume => resume.id === selectedApplication?.resume_id);
  const recipientEmail = selectedApplication?.recipient_email.trim() || '';
  const selectedRecipient = recipientEmail.toLowerCase();
  const sendBlocker = demo || selectedApplication?.demo
    ? { label: 'Envío deshabilitado en demostración', message: 'Esta postulación es de demostración y no permite envíos reales.' }
    : busy
      ? { label: 'Operación en curso', message: 'Esperá a que termine la operación en curso antes de enviar esta postulación.' }
      : !recipientEmail
        ? { label: 'Falta el correo de la empresa', message: 'Falta la dirección de correo de postulación. Hay que revisar el canal publicado por la empresa; no se puede inventar una dirección ni habilitar el envío sin ese dato.' }
        : !selectedApplication?.resume_id
          ? { label: 'Falta seleccionar un CV', message: 'Esta postulación no tiene un CV seleccionado. Necesita un CV asociado antes de poder enviarse.' }
          : !consent
            ? { label: 'Falta autorizar el envío', message: 'Marcá la casilla para autorizar el envío de este mensaje y tu CV al destinatario indicado.' }
            : null;
  const followupsStopped = selectedApplication?.followups_stopped || stoppedRecipients.includes(selectedRecipient);
  const shown = applications.filter(item => (filter === 'all' || item.status === filter) && `${item.company} ${item.role} ${item.recipient_email}`.toLowerCase().includes(query.toLowerCase()));
  const confirmed = applications.filter(item => !item.demo && !item.delivery_uncertain && (item.status === 'sent' || item.status === 'responded') && item.provider_message_id && item.provider_confirmed_at).length;
  const stats = [{ label: 'Postulaciones', count: applications.length, icon: 'layers-outline' as const }, { label: 'Para revisar', count: applications.filter(item => item.status === 'pending').length, icon: 'time-outline' as const }, { label: 'Envíos confirmados', count: confirmed, icon: 'checkmark-done-outline' as const }];
  const close = () => { if (stopping) return; setSelected(null); setConsent(false); setStopFeedback(null); setSendFeedback(null); };
  const send = async () => {
    if (!selectedApplication || !consent || demo || selectedApplication.demo || !selectedApplication.resume_id || !selectedApplication.recipient_email.trim() || busy || selectedApplication.status !== 'pending' || selectedApplication.delivery_uncertain || selectedApplication.send_attempt_id) return;
    setSendFeedback(null);
    try { await onSend(selectedApplication.id); }
    catch (error) { setSendFeedback({ applicationId: selectedApplication.id, message: error instanceof Error ? error.message : 'No se confirmó el envío. Revisá el estado antes de volver a intentarlo.' }); }
    finally { setConsent(false); }
  };
  const stopFollowups = async () => {
    if (!selectedApplication || !onStopFollowups || stopping || busy || demo || selectedApplication.demo || followupsStopped) return;
    const recipient = selectedRecipient;
    setStopping(true); setStopFeedback(null);
    try {
      await onStopFollowups(selectedApplication.id);
      setStoppedRecipients(current => current.includes(recipient) ? current : [...current, recipient]);
      setStopFeedback({ text: 'El servidor confirmó la detención de futuros reenvíos a esta dirección en todas tus búsquedas. Una operación ya iniciada podría completarse.', error: false });
    } catch (error) { setStopFeedback({ text: error instanceof Error ? error.message : 'No se confirmó la detención. Revisá el estado antes de volver a intentarlo.', error: true }); }
    finally { setStopping(false); }
  };
  return <View style={{ flex: 1, backgroundColor: colors.bg }}><ScrollView contentContainerStyle={[styles.content, { paddingHorizontal: width < 650 ? 20 : 40 }]}>
    <ScreenHeader eyebrow="Cada paso, registrado" title="Mis postulaciones" subtitle="Revisá tus mensajes y seguí cada oportunidad desde un solo lugar." />
    <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 12, marginBottom: 28 }}>{stats.map(stat => <Card key={stat.label} style={{ flex: 1, minWidth: width < 650 ? 90 : 170, padding: width < 650 ? 14 : 20 }}><View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 13 }}><Ionicons name={stat.icon} size={19} color={colors.primary} /><Text style={{ fontSize: 25, fontWeight: '500', color: colors.text }}>{stat.count.toString().padStart(2, '0')}</Text></View><Text style={{ fontSize: 10, lineHeight: 17, color: colors.muted }}>{stat.label}</Text></Card>)}</View>
    <Card style={{ padding: 0, overflow: 'hidden' }}>
      <View style={{ padding: 22, gap: 18 }}><View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}><View style={[styles.query, { backgroundColor: colors.bg, borderColor: colors.border }]}><Ionicons name="search-outline" size={16} color={colors.muted} /><TextInput value={query} onChangeText={setQuery} accessibilityLabel="Buscar postulaciones" placeholder="Buscar empresa o puesto" placeholderTextColor={colors.muted} style={{ flex: 1, fontSize: 12, color: colors.text, minHeight: 35 }} />{query ? <IconButton icon="close-outline" onPress={() => setQuery('')} accessibilityLabel="Limpiar búsqueda" /> : null}</View>{width >= 650 ? <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}><Ionicons name="shield-checkmark-outline" size={13} color={colors.primary} /><Text style={{ fontSize: 10, color: colors.muted }}>Historial verificable</Text></View> : null}</View>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 6 }}>{filters.map(item => <Pressable key={item.key} onPress={() => setFilter(item.key)} accessibilityRole="button" accessibilityState={{ selected: filter === item.key }} style={[styles.filter, { backgroundColor: filter === item.key ? colors.primarySoft : 'transparent' }]}><Text style={{ fontSize: 11, fontWeight: filter === item.key ? '600' : '400', color: filter === item.key ? colors.primary : colors.muted }}>{item.label}</Text></Pressable>)}</ScrollView>
      </View>
      {width >= 900 && shown.length ? <View style={[styles.tableHead, { backgroundColor: colors.bg, borderColor: colors.border }]}><Text style={[styles.columnLabel, { flex: 1.5, color: colors.muted }]}>EMPRESA / PUESTO</Text><Text style={[styles.columnLabel, { flex: 1, color: colors.muted }]}>FECHA / HORA</Text><Text style={[styles.columnLabel, { width: 130, color: colors.muted }]}>ESTADO</Text><View style={{ width: 24 }} /></View> : null}
      {shown.map(item => { const status = stateOf(item); return <Pressable key={item.id} onPress={() => { setSelected(item); setConsent(false); setStopFeedback(null); setSendFeedback(null); }} accessibilityRole="button" accessibilityLabel={`Ver ${deliveryLabel(item).toLowerCase()} a ${item.company}, ${status.label}`} style={({ pressed }) => [styles.applicationRow, { borderTopColor: colors.border, backgroundColor: pressed ? colors.surfaceAlt : 'transparent' }]}>
        <View style={[styles.companyIcon, { backgroundColor: colors.surfaceAlt }]}><Text style={{ fontSize: 17, color: colors.primary, fontWeight: '600' }}>{item.company.trim().slice(0, 1).toUpperCase()}</Text></View>
        <View style={{ flex: width >= 900 ? 1.5 : 1, gap: 5 }}><View style={{ flexDirection: 'row', gap: 7, alignItems: 'center', flexWrap: 'wrap' }}><Text style={{ fontSize: 13, fontWeight: '600', color: colors.text }}>{item.company}</Text>{item.demo ? <Badge label="Demo" tone="warning" /> : null}</View><Text style={{ fontSize: 11, color: colors.muted }}>{item.role}</Text><Text style={{ color: colors.muted, fontSize: 10 }}>{deliveryLabel(item)}</Text>{width < 900 ? <Text style={{ color: colors.muted, fontSize: 10 }}>{formatDate(deliveryDate(item))}</Text> : <Text numberOfLines={1} style={{ color: colors.muted, fontSize: 10 }}>{item.recipient_email}</Text>}</View>
        {width >= 900 ? <Text style={{ fontSize: 11, color: colors.muted, flex: 1 }}>{formatDate(deliveryDate(item))}</Text> : null}<View style={{ width: width >= 900 ? 130 : undefined }}><Badge label={status.label} tone={status.tone} /></View><Ionicons name="chevron-forward-outline" color={colors.muted} size={15} />
      </Pressable>; })}
      {!shown.length ? <EmptyState icon="mail-open-outline" title={query || filter !== 'all' ? 'No encontramos coincidencias' : 'Tu próxima oportunidad empieza acá'} description={query || filter !== 'all' ? 'Probá con otra empresa, puesto o estado.' : 'Las postulaciones preparadas por tu asistente aparecerán acá para que puedas revisarlas.'} /> : null}
    </Card>
    <View style={{ flexDirection: 'row', gap: 8, marginTop: 18, paddingHorizontal: 2 }}><Ionicons name="information-circle-outline" size={14} color={colors.muted} /><Text style={{ flex: 1, fontSize: 10, lineHeight: 18, color: colors.muted }}>Cada envío o reenvío tiene su propio registro, mensaje, CV y confirmación. Se marca como enviado únicamente cuando el proveedor confirma la operación. Los reenvíos autorizados esperan al menos 72 horas desde la última confirmación a ese correo.{demo ? ' Los registros de demostración no representan envíos reales.' : ''}</Text></View>
  </ScrollView>
  <Modal visible={!!selectedApplication} animationType="fade" transparent onRequestClose={close}><View style={styles.overlay}><View style={[styles.modal, { backgroundColor: colors.surface, borderColor: colors.border, maxHeight: '90%' }]}>{selectedApplication ? <>
    <View style={{ padding: 23, paddingBottom: 12, flexDirection: 'row', alignItems: 'center', gap: 15 }}><View style={{ flex: 1, gap: 7 }}><Text style={{ color: colors.muted, fontSize: 9, letterSpacing: 1.5 }}>DETALLE DE LA POSTULACIÓN</Text><Text style={{ color: colors.text, fontSize: 23, fontWeight: '500', letterSpacing: -.5 }}>{selectedApplication.company}</Text><Text style={{ color: colors.muted, fontSize: 12 }}>{selectedApplication.role} · {deliveryLabel(selectedApplication)}</Text></View><IconButton icon="close-outline" onPress={close} accessibilityLabel="Cerrar detalle" size={23} disabled={stopping} /></View>
    <ScrollView contentContainerStyle={{ padding: 23, paddingTop: 10 }}><View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 7 }}><Badge label={stateOf(selectedApplication).label} tone={stateOf(selectedApplication).tone} />{selectedApplication.demo ? <Badge label="Datos de demostración · sin envío real" tone="warning" /> : null}</View><Divider />
      <View style={{ gap: 14 }}>{selectedApplication.sender_email ? <Info label="REMITENTE DEL REGISTRO" value={selectedApplication.sender_email} /> : null}<Info label="DESTINATARIO" value={recipientEmail || 'Sin correo de postulación'} /><Info label="FECHA Y HORA DEL REGISTRO" value={formatDate(selectedApplication.created_at)} />{selectedApplication.attempted_at ? <Info label="FECHA Y HORA DEL INTENTO" value={formatDate(selectedApplication.attempted_at)} /> : null}{selectedApplication.parent_application_id ? <Info label="POSTULACIÓN ORIGINAL" value={selectedApplication.parent_application_id} /> : null}<Info label="ASUNTO" value={selectedApplication.subject} /></View>
      <Text style={{ color: colors.muted, fontSize: 9, letterSpacing: 1, fontWeight: '600', marginTop: 24, marginBottom: 10 }}>MENSAJE</Text><View style={{ backgroundColor: colors.bg, borderRadius: 12, padding: 18 }}><Text selectable style={{ color: colors.text, fontSize: 12, lineHeight: 22 }}>{selectedApplication.body || 'El mensaje todavía no fue redactado.'}</Text></View>
      <View style={{ flexDirection: 'row', gap: 11, padding: 14, borderColor: colors.border, borderWidth: 1, borderRadius: 11, marginTop: 15 }}><Ionicons name="document-text-outline" size={20} color={colors.primary} /><View style={{ flex: 1 }}><Text style={{ fontSize: 11, fontWeight: '600', color: colors.text }}>{selectedResume?.name || (selectedApplication.resume_id ? 'CV de este registro' : 'Sin CV seleccionado')}</Text><Text style={{ fontSize: 10, color: colors.muted, marginTop: 4 }}>{selectedResume?.file_name || (selectedApplication.resume_id ? `Versión: ${selectedApplication.resume_id}` : 'Seleccioná un CV antes de postularte.')}</Text></View></View>
      {selectedApplication.provider_message_id && selectedApplication.provider_confirmed_at && !selectedApplication.demo ? <View style={{ backgroundColor: colors.primarySoft, borderRadius: 12, padding: 16, marginTop: 16, gap: 9 }}><Text style={{ fontSize: 11, color: colors.primary, fontWeight: '600' }}>Confirmación del proveedor</Text><Text selectable style={{ fontSize: 10, lineHeight: 18, color: colors.text }}>ID: {selectedApplication.provider_message_id}</Text><Text style={{ fontSize: 10, color: colors.muted }}>{new Date(selectedApplication.provider_confirmed_at).toLocaleString('es-AR')}</Text></View> : <Text style={{ color: colors.muted, fontSize: 10, lineHeight: 18, marginTop: 16 }}>No existe una confirmación de envío del proveedor para este registro.</Text>}
      {sendFeedback?.applicationId === selectedApplication.id ? <Text accessibilityRole="alert" style={{ color: colors.danger, fontSize: 11, lineHeight: 19, marginTop: 16 }}>{sendFeedback.message}</Text> : null}
      {selectedApplication.error_message ? <Text style={{ color: colors.danger, fontSize: 11, lineHeight: 19, marginTop: 16 }}>{selectedApplication.error_message}</Text> : null}
      {selectedApplication.delivery_uncertain || (selectedApplication.status === 'pending' && selectedApplication.send_attempt_id) ? <Text style={{ color: colors.warning, fontSize: 11, lineHeight: 19, marginTop: 16 }}>Este intento requiere verificar el resultado con el proveedor. No se habilita un nuevo envío ni se repite automáticamente mientras el resultado esté sin resolver.</Text> : null}
      {onStopFollowups && !demo && !selectedApplication.demo && (selectedApplication.status === 'sent' || selectedApplication.status === 'responded') && selectedApplication.provider_message_id && selectedApplication.provider_confirmed_at ? <View style={{ marginTop: 20, gap: 10 }}><Button label={followupsStopped ? 'Reenvíos detenidos a este correo' : 'Detener reenvíos a esta empresa'} icon="hand-left-outline" variant="secondary" disabled={followupsStopped || busy || stopping} loading={stopping} onPress={() => void stopFollowups()} /><Text style={{ color: colors.muted, fontSize: 10, lineHeight: 18 }}>Se detienen futuros reenvíos a {selectedApplication.recipient_email} en todas tus búsquedas. Usá esta opción si respondieron o ya no querés insistir.</Text>{selectedApplication.followups_stopped_at ? <Text style={{ color: colors.muted, fontSize: 10 }}>Detenidos desde {formatDate(selectedApplication.followups_stopped_at)}</Text> : null}{stopFeedback ? <Text accessibilityRole="alert" style={{ color: stopFeedback.error ? colors.danger : colors.primary, fontSize: 11, lineHeight: 19 }}>{stopFeedback.text}</Text> : null}</View> : null}
      {selectedApplication.status === 'pending' && !selectedApplication.send_attempt_id && !selectedApplication.delivery_uncertain ? <View style={{ marginTop: 22, gap: 14 }}><Pressable onPress={() => setConsent(value => !value)} accessibilityRole="checkbox" accessibilityState={{ checked: consent }} disabled={demo || selectedApplication.demo} style={{ flexDirection: 'row', gap: 10, alignItems: 'flex-start' }}><Ionicons name={consent ? 'checkbox' : 'square-outline'} size={20} color={demo || selectedApplication.demo ? colors.muted : colors.primary} /><Text style={{ fontSize: 10, lineHeight: 18, flex: 1, color: colors.muted }}>Autorizo el envío de este mensaje y mi CV a este destinatario. Cuenta dentro del máximo total de 10 correos diarios de mi cuenta.</Text></Pressable><Info label="DESTINATARIO DEL ENVÍO" value={recipientEmail || 'Falta el correo de la empresa'} />{sendBlocker ? <Text accessibilityRole="alert" style={{ color: colors.warning, fontSize: 11, lineHeight: 19 }}>{sendBlocker.message}</Text> : null}<Button label={sendBlocker?.label || 'Autorizar y enviar postulación'} icon="paper-plane-outline" disabled={!!sendBlocker} loading={busy} onPress={() => void send()} /><Text style={{ color: colors.muted, fontSize: 10, lineHeight: 18 }}>El servidor debe validar el destinatario y los demás requisitos antes de enviar. Que el correo aparezca acá no significa que esté verificado.</Text></View> : null}
    </ScrollView>
  </> : null}</View></View></Modal>
  </View>;
}
function Info({ label, value }: { label: string; value: string }) { const { colors } = useTheme(); return <View style={{ gap: 6 }}><Text style={{ color: colors.muted, fontSize: 9, fontWeight: '600', letterSpacing: .8 }}>{label}</Text><Text selectable style={{ color: colors.text, fontSize: 12, lineHeight: 19 }}>{value}</Text></View>; }
const styles = StyleSheet.create({ content: { flexGrow: 1, paddingTop: 36, paddingBottom: 38, width: '100%', maxWidth: 1180, alignSelf: 'center' }, query: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: 9, paddingLeft: 13, paddingRight: 6, borderRadius: 9, borderWidth: 1, maxWidth: 400 }, filter: { paddingHorizontal: 13, paddingVertical: 9, borderRadius: 7 }, tableHead: { flexDirection: 'row', paddingVertical: 12, paddingHorizontal: 22, paddingLeft: 82, gap: 14, borderTopWidth: 1 }, columnLabel: { fontSize: 9, fontWeight: '600', letterSpacing: 1 }, applicationRow: { flexDirection: 'row', alignItems: 'center', gap: 14, padding: 22, borderTopWidth: 1 }, companyIcon: { width: 43, height: 43, borderRadius: 12, alignItems: 'center', justifyContent: 'center' }, overlay: { flex: 1, backgroundColor: '#10241BC0', alignItems: 'center', justifyContent: 'center', padding: 20 }, modal: { width: '100%', maxWidth: 620, borderRadius: 22, borderWidth: 1, overflow: 'hidden' } });

export { ApplicationsScreen };
