import React, { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import type { JobSearch, Resume } from '../types';
import { api, grantSendingConsent, revokeSendingConsent, sendingAuthorizationText, type MailPolicy } from '../services/backend';
import { useTheme } from '../theme/theme';
import { sendingPermission, sendingPermissionLabel } from '../state/automation';
import { Badge, Button, Divider, Field, IconButton } from './ui';

interface Props {
  search: JobSearch | null;
  resumes: Resume[];
  demo: boolean;
  onClose: () => void;
  onChanged: (search: JobSearch) => void;
}
interface PermissionRecord { id: string; search_id: string; resume_id: string | null; email_connection_id: string; authorized_sources: string[]; daily_limit: number; repeat_every_days?: 0 | 3; policy_version?: string; expires_at: string; revoked_at: string | null; status?: string }
interface Integrations {
  sources: { id: string; name: string }[];
  email_connections: { id: string; email: string; status: string }[];
  sending_enabled?: boolean;
  mail_policy?: MailPolicy;
}
const expiryDefault = () => new Date(Date.now() + 30 * 86400000).toISOString().slice(0, 10);

function Choice({ selected, label, detail, disabled, multiple, onPress }: { selected: boolean; label: string; detail?: string; disabled?: boolean; multiple?: boolean; onPress: () => void }) {
  const { colors } = useTheme();
  return <Pressable accessibilityRole={multiple ? 'checkbox' : 'radio'} accessibilityState={{ checked: selected, disabled }} accessibilityLabel={label} disabled={disabled} onPress={onPress} style={[styles.choice, { borderColor: selected ? colors.primary : colors.border, backgroundColor: selected ? colors.primarySoft : colors.bg, opacity: disabled ? .6 : 1 }]}>
    <Ionicons name={multiple ? selected ? 'checkbox' : 'square-outline' : selected ? 'radio-button-on-outline' : 'radio-button-off-outline'} size={21} color={selected ? colors.primary : colors.muted} />
    <View style={{ flex: 1 }}><Text style={{ color: colors.text, fontSize: 12, lineHeight: 19, fontWeight: selected ? '600' : '400' }}>{label}</Text>{detail ? <Text style={{ color: colors.muted, fontSize: 10, lineHeight: 17, marginTop: 3 }}>{detail}</Text> : null}</View>
  </Pressable>;
}

export default function ConsentModal({ search, resumes, demo, onClose, onChanged }: Props) {
  const { colors } = useTheme();
  const [integrations, setIntegrations] = useState<Integrations>({ sources: [], email_connections: [] });
  const [loading, setLoading] = useState(false);
  const [permissions, setPermissions] = useState<PermissionRecord[]>([]);
  const [working, setWorking] = useState<'grant' | 'revoke' | null>(null);
  const [resumeId, setResumeId] = useState('');
  const [connectionId, setConnectionId] = useState('');
  const [sourceIds, setSourceIds] = useState<string[]>([]);
  const [expiry, setExpiry] = useState(expiryDefault);
  const [consent, setConsent] = useState(false);
  const [repeat, setRepeat] = useState(true);
  const [feedback, setFeedback] = useState<{ text: string; error: boolean } | null>(null);
  const requestVersion = useRef(0);
  const busyLock = useRef(false);
  const isDemo = demo || !!search?.demo;
  const consentId = (search as (JobSearch & { consent_id?: string | null }) | null)?.consent_id;
  const registered = !!consentId;
  const currentPermission = permissions.find(permission => permission.id === consentId);
  const permissionState = search ? sendingPermission({ ...search, consent_expires_at: currentPermission?.expires_at || search.consent_expires_at, consent_revoked_at: currentPermission?.revoked_at || search.consent_revoked_at }) : 'unknown';
  const connected = integrations.email_connections.filter(account => account.status === 'connected');
  const eligibleResumes = resumes.filter(resume => isDemo || !resume.demo);
  const repeatEveryDays = repeat ? 3 : 0;
  const authorizationText = sendingAuthorizationText(repeatEveryDays);

  const load = async (version: number) => {
    setLoading(true);
    try {
      const [result, records] = await Promise.all([api<Integrations>('/api/integrations'), api<PermissionRecord[]>('/api/mail/consents')]);
      if (requestVersion.current !== version) return;
      const accounts = result.email_connections.filter(account => account.status === 'connected');
      setIntegrations(result); setPermissions(records);
      setConnectionId(accounts.length === 1 ? accounts[0].id : '');
    } catch (caught) {
      if (requestVersion.current === version) setFeedback({ text: caught instanceof Error ? caught.message : 'No pudimos consultar tus conexiones. Intentá nuevamente.', error: true });
    } finally { if (requestVersion.current === version) setLoading(false); }
  };

  useEffect(() => {
    const version = ++requestVersion.current;
    setIntegrations({ sources: [], email_connections: [] }); setPermissions([]); setConnectionId(''); setSourceIds([]);
    setResumeId(search?.preferred_resume_id || eligibleResumes.find(resume => resume.is_default)?.id || eligibleResumes[0]?.id || '');
    setExpiry(expiryDefault()); setConsent(false); setRepeat(true); setFeedback(null); setLoading(false);
    if (search && !isDemo) void load(version);
    return () => { requestVersion.current++; };
  }, [search?.id, isDemo]);

  const close = () => { if (!busyLock.current) onClose(); };

  const grant = async () => {
    if (!search || isDemo || busyLock.current || loading) return;
    setFeedback(null);
    if (!eligibleResumes.some(resume => resume.id === resumeId)) { setFeedback({ text: 'Elegí un currículum de tu cuenta para autorizar los envíos.', error: true }); return; }
    if (!connected.some(account => account.id === connectionId)) { setFeedback({ text: 'Elegí una cuenta de correo conectada.', error: true }); return; }
    if (!sourceIds.length || sourceIds.some(id => !integrations.sources.some(source => source.id === id))) { setFeedback({ text: 'Elegí al menos una fuente autorizada.', error: true }); return; }
    if (!consent) { setFeedback({ text: 'Marcá la autorización expresa antes de continuar.', error: true }); return; }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(expiry)) { setFeedback({ text: 'Ingresá el vencimiento con formato AAAA-MM-DD.', error: true }); return; }
    const date = new Date(`${expiry}T23:59:59.000Z`);
    if (Number.isNaN(date.getTime()) || date.toISOString().slice(0, 10) !== expiry) { setFeedback({ text: 'Ingresá una fecha de vencimiento válida.', error: true }); return; }
    if (date.getTime() <= Date.now() || date.getTime() > Date.now() + 90 * 86400000) { setFeedback({ text: 'El vencimiento debe estar en el futuro y dentro de los próximos 90 días.', error: true }); return; }
    busyLock.current = true; setWorking('grant');
    try {
      const result = await grantSendingConsent({ search_id: search.id, resume_id: resumeId, email_connection_id: connectionId, allowed_sources: sourceIds, expires_at: date.toISOString(), repeat_every_days: repeatEveryDays });
      const registeredPermission = result.consent as unknown as PermissionRecord;
      setPermissions(current => [registeredPermission, ...current.filter(item => item.id !== registeredPermission.id)]);
      onChanged({ ...result.search, consent_expires_at: registeredPermission.expires_at, consent_revoked_at: registeredPermission.revoked_at, consent_repeat_every_days: registeredPermission.repeat_every_days ?? null, consent_daily_limit: registeredPermission.daily_limit });
      setConsent(false);
      setFeedback({ text: result.message, error: false });
    } catch (caught) { setFeedback({ text: caught instanceof Error ? caught.message : 'No se confirmó la autorización. Revisá el estado antes de volver a intentarlo.', error: true }); }
    finally { busyLock.current = false; setWorking(null); }
  };

  const revoke = async () => {
    if (!search || !consentId || isDemo || busyLock.current) return;
    busyLock.current = true; setWorking('revoke'); setFeedback(null);
    try {
      const result = await revokeSendingConsent(consentId);
      if (!result.revoked) throw new Error('El servidor no confirmó la revocación. Revisá la autorización antes de volver a intentarlo.');
      onChanged({ ...search, auto_apply: false, consent_id: null, consent_expires_at: null, consent_revoked_at: null, consent_repeat_every_days: null, consent_daily_limit: null });
      setConsent(false);
      setFeedback({ text: 'El servidor confirmó la revocación. Las futuras postulaciones requieren aprobación manual. Una operación ya iniciada podría completarse.', error: false });
    } catch (caught) { setFeedback({ text: caught instanceof Error ? caught.message : 'No pudimos revocar la autorización.', error: true }); }
    finally { busyLock.current = false; setWorking(null); }
  };

  return <Modal visible={!!search} transparent animationType="fade" onRequestClose={close}>
    <View style={styles.overlay}><View style={[styles.modal, { backgroundColor: colors.surface, borderColor: colors.border }]}>
      <View style={styles.header}><View style={{ flex: 1, gap: 7 }}><Text style={{ color: colors.muted, fontSize: 9, letterSpacing: 1.4 }}>PERMISOS DE ESTA BÚSQUEDA</Text><Text style={{ color: colors.text, fontSize: 22, letterSpacing: -.5, fontWeight: '600' }}>Envíos automáticos</Text><Text style={{ color: colors.muted, fontSize: 12, lineHeight: 20 }}>{search?.name}</Text></View><IconButton icon="close-outline" accessibilityLabel="Cerrar permisos de envío" onPress={close} disabled={!!working} /></View>
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        <View style={[styles.summary, { backgroundColor: colors.primarySoft }]}><Ionicons name="shield-checkmark-outline" size={22} color={colors.primary} /><View style={{ flex: 1 }}><Text style={{ color: colors.text, fontSize: 13, lineHeight: 20, fontWeight: '600' }}>Máximo 10 correos diarios en total</Text><Text style={{ color: colors.muted, fontSize: 11, lineHeight: 19, marginTop: 6 }}>El límite es compartido por todas tus búsquedas y los envíos manuales. Incluye las nuevas postulaciones y los reenvíos; se envían menos si no hay suficientes vacantes aptas. En cada ejecución se atienden primero las nuevas oportunidades.</Text></View></View>
        <Text style={{ color: colors.muted, fontSize: 10, lineHeight: 18 }}>{search?.frequency === 'daily' ? 'Todos los días' : 'Días elegidos'} · {search?.schedule_time.slice(0, 5)} · {search?.timezone}. {integrations.mail_policy ? `El día del límite usa ${integrations.mail_policy.timezone}, para toda tu cuenta.` : 'La zona horaria del límite se consulta al servidor al cargar tus permisos.'}</Text>
        {!isDemo && integrations.sending_enabled === false ? <View style={[styles.feedback, { backgroundColor: `${colors.warning}12` }]}><Text style={{ color: colors.warning, fontSize: 12, lineHeight: 20 }}>El servicio de correo todavía tiene los envíos desactivados. Podés guardar la autorización; comenzará a operar cuando el servicio esté habilitado y llegue el horario de búsqueda.</Text></View> : null}
        {isDemo ? <View style={[styles.feedback, { backgroundColor: `${colors.warning}12` }]}><Text style={{ color: colors.warning, fontSize: 12, lineHeight: 20 }}>Modo demostración. No se conceden permisos reales, no se buscan vacantes y no se envían correos.</Text></View> : null}
        {feedback ? <View style={[styles.feedback, { backgroundColor: feedback.error ? `${colors.danger}12` : colors.primarySoft }]}><Text accessibilityRole="alert" style={{ color: feedback.error ? colors.danger : colors.primary, fontSize: 12, lineHeight: 20 }}>{feedback.text}</Text></View> : null}
        {registered ? <View style={{ gap: 15 }}><Badge label={loading ? 'Consultando autorización' : sendingPermissionLabel(permissionState)} tone={permissionState === 'active' ? 'success' : 'warning'} icon="shield-checkmark-outline" />
            {currentPermission ? <View style={{ gap: 7 }}><Text style={{ color: colors.text, fontSize: 12 }}>CV: {resumes.find(resume => resume.id === currentPermission.resume_id)?.name || 'Versión registrada'}</Text><Text style={{ color: colors.text, fontSize: 12 }}>Remitente: {integrations.email_connections.find(account => account.id === currentPermission.email_connection_id)?.email || 'Cuenta registrada'}</Text><Text style={{ color: colors.muted, fontSize: 11 }}>Fuentes: {currentPermission.authorized_sources.map(id => integrations.sources.find(source => source.id === id)?.name || id).join(', ')}</Text><Text style={{ color: colors.muted, fontSize: 11 }}>Reenvíos: {currentPermission.repeat_every_days === 3 ? 'cada 3 días, si la vacante sigue vigente y apta' : currentPermission.repeat_every_days === 0 ? 'desactivados' : 'permiso pendiente de verificar'}</Text><Text style={{ color: colors.muted, fontSize: 11 }}>Límite: 10 correos por día en toda tu cuenta</Text><Text style={{ color: colors.muted, fontSize: 11 }}>Vence: {new Date(currentPermission.expires_at).toLocaleString('es-AR')}</Text></View> : null}<Text style={{ color: colors.muted, fontSize: 12, lineHeight: 21 }}>Los permisos anteriores no habilitan reenvíos. Para cambiar el currículum, la cuenta, las fuentes, los reenvíos o el vencimiento, revocá el permiso y creá una autorización nueva.</Text><Button label="Revocar envíos automáticos" variant="danger" icon="close-circle-outline" onPress={() => void revoke()} disabled={isDemo || !!working} loading={working === 'revoke'} /></View> : <>
          <Text style={[styles.label, { color: colors.text }]}>Currículum que se adjuntará</Text>
          {eligibleResumes.map(resume => <Choice key={resume.id} label={resume.name} detail={resume.file_name} selected={resumeId === resume.id} onPress={() => { setResumeId(resume.id); setConsent(false); }} disabled={isDemo || !!working} />)}
          {!eligibleResumes.length ? <Text style={{ color: colors.muted, fontSize: 12, lineHeight: 20 }}>Cargá primero un currículum desde Mi perfil.</Text> : null}
          <Text style={[styles.label, { color: colors.text }]}>Cuenta de correo</Text>
          {loading ? <View style={styles.loading}><ActivityIndicator color={colors.primary} /><Text style={{ color: colors.muted, fontSize: 11 }}>Consultando conexiones autorizadas…</Text></View> : connected.map(account => <Choice key={account.id} label={account.email} selected={connectionId === account.id} onPress={() => { setConnectionId(account.id); setConsent(false); }} disabled={!!working} />)}
          {!loading && !connected.length ? <Text style={{ color: colors.muted, fontSize: 12, lineHeight: 20 }}>Conectá tu correo de forma segura desde Mi perfil antes de autorizar envíos.</Text> : null}
          <Text style={[styles.label, { color: colors.text }]}>Fuentes autorizadas</Text>
          {integrations.sources.map(source => <Choice key={source.id} label={source.name} selected={sourceIds.includes(source.id)} multiple disabled={!!working} onPress={() => { setSourceIds(current => current.includes(source.id) ? current.filter(id => id !== source.id) : [...current, source.id]); setConsent(false); }} />)}
          {!loading && !integrations.sources.length ? <Text style={{ color: colors.muted, fontSize: 12, lineHeight: 20 }}>Todavía no hay fuentes autorizadas disponibles. El permiso no puede activarse hasta que haya una integración habilitada.</Text> : null}
          <Divider />
          <Choice label="Repetir al mismo correo cada 3 días" detail="Se esperan al menos 72 horas desde el último envío confirmado a esa dirección, entre todas tus búsquedas. Solo se repite si la vacante sigue vigente y cumple tu perfil, con este permiso activo. Los envíos con respuesta, error o resultado incierto quedan para revisión manual; no se repiten automáticamente." selected={repeat} multiple disabled={isDemo || !!working || loading} onPress={() => { setRepeat(value => !value); setConsent(false); }} />
          <Field label="Vencimiento · AAAA-MM-DD" value={expiry} onChangeText={value => { setExpiry(value); setConsent(false); }} placeholder="2026-11-12" editable={!isDemo && !working} style={{ flex: 0 }} />
          <Text style={{ color: colors.muted, fontSize: 10, lineHeight: 18 }}>Vence a las 23:59 UTC de la fecha elegida, dentro de los próximos 90 días. Podés revocar el permiso cuando quieras.</Text>
          <Choice label={authorizationText} detail={`Confirmo el CV, la cuenta, las fuentes, el máximo total de 10 correos diarios, ${repeat ? 'los reenvíos cada 3 días' : 'que no habrá reenvíos automáticos'} y el vencimiento indicados arriba.`} selected={consent} multiple disabled={isDemo || !!working || loading} onPress={() => setConsent(value => !value)} />
          <Button label={isDemo ? 'Autorización deshabilitada en demo' : 'Confirmar autorización'} icon="shield-checkmark-outline" onPress={() => void grant()} disabled={isDemo || !!working || loading || !consent || !eligibleResumes.length || !connected.length || !sourceIds.length} loading={working === 'grant'} />
        </>}
      </ScrollView>
    </View></View>
  </Modal>;
}

const styles = StyleSheet.create({ overlay: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(8, 19, 32, .65)', padding: 20 }, modal: { width: '100%', maxWidth: 620, maxHeight: '90%', borderRadius: 22, borderWidth: 1, overflow: 'hidden' }, header: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 23, paddingTop: 23, paddingBottom: 16 }, content: { paddingHorizontal: 23, paddingBottom: 25, gap: 11 }, summary: { flexDirection: 'row', gap: 12, padding: 16, borderRadius: 12, marginBottom: 8 }, feedback: { padding: 14, borderRadius: 11, marginBottom: 7 }, label: { fontSize: 12, fontWeight: '600', marginTop: 14, marginBottom: 2 }, choice: { flexDirection: 'row', alignItems: 'flex-start', gap: 11, borderWidth: 1, borderRadius: 11, padding: 13 }, loading: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 12 } });
