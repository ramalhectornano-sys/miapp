import React, { useEffect, useRef, useState } from 'react';
import {
  Alert,
  Image,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  View,
  useWindowDimensions,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Profile, Resume, MailConnection } from '../types';
import { useTheme } from '../theme/theme';
import {
  Badge,
  Button,
  Card,
  Divider,
  EmptyState,
  Field,
  IconButton,
  ScreenHeader,
  SectionHeader,
} from '../components/ui';

interface Props {
  profile: Profile;
  resumes: Resume[];
  busy: boolean;
  onSave: (profile: Profile) => Promise<void>;
  onUpload: () => Promise<void>;
  onPhoto: () => Promise<void>;
  photoUrl?: string;
  onExtract: (id: string) => Promise<void>;
  onDeleteResume: (id: string) => Promise<void>;
  onOpenResume: (id: string) => Promise<void>;
  onConnectMail: () => Promise<void>;
  onDeleteAccount: () => Promise<void>;
  onSignOut: () => void;
  demo: boolean;
  email?: string;
  mailConnections?: MailConnection[];
  onThemeToggle: () => void;
  dark: boolean;
  onMakeDefault?: (id: string) => Promise<void>;
}

const makeId = () => `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
const fileSize = (bytes: number) => bytes < 1024 * 1024
  ? `${Math.max(1, Math.round(bytes / 1024))} KB`
  : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;

export default function ProfileScreen(props: Props) {
  const { colors, preference, setPreference } = useTheme();
  const { width } = useWindowDimensions();
  const wide = width > 900;
  const connectedMail = (props.mailConnections || []).filter(account => account.status === 'connected');
  const [draft, setDraft] = useState<Profile>(props.profile);
  const [working, setWorking] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteText, setDeleteText] = useState('');
  const disabled = props.busy || working !== null;
  const dirty = JSON.stringify(draft) !== JSON.stringify(props.profile);

  const previousProfile = useRef(props.profile);
  useEffect(() => {
    const previous = { ...previousProfile.current, photo_path: null };
    const next = { ...props.profile, photo_path: null };
    if (JSON.stringify(previous) === JSON.stringify(next)) setDraft(current => ({ ...current, photo_path: props.profile.photo_path }));
    else setDraft(props.profile);
    previousProfile.current = props.profile;
  }, [props.profile]);

  const update = (change: Partial<Profile>) => {
    setDraft(current => ({ ...current, ...change }));
    setSaved(false);
  };

  const run = async (name: string, action: () => Promise<void>) => {
    if (disabled) return;
    setError('');
    setWorking(name);
    try {
      await action();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'No pudimos completar la operación. Intentá nuevamente.');
    } finally {
      setWorking(null);
    }
  };

  const save = () => run('save', async () => {
    if (!draft.full_name.trim()) throw new Error('Completá tu nombre para guardar el perfil.');
    await props.onSave({
      ...draft,
      full_name: draft.full_name.trim(),
      city: draft.city.trim(),
      headline: draft.headline.trim(),
    });
    setSaved(true);
  });

  const removeResume = (resume: Resume) => {
    if (Platform.OS === 'web') {
      const confirmed = typeof globalThis.confirm === 'function' && globalThis.confirm(`¿Eliminar «${resume.name}»? Esta acción no se puede deshacer.`);
      if (confirmed) void run(`delete-${resume.id}`, () => props.onDeleteResume(resume.id));
      return;
    }
    Alert.alert(
    'Eliminar currículum',
    `Se eliminará «${resume.name}». Esta acción no se puede deshacer.`,
    [
      { text: 'Cancelar', style: 'cancel' },
      { text: 'Eliminar', style: 'destructive', onPress: () => { void run(`delete-${resume.id}`, () => props.onDeleteResume(resume.id)); } },
    ],
    );
  };

  const initial = draft.full_name.trim().split(/\s+/).filter(Boolean).slice(0, 2).map(part => part[0]).join('').toUpperCase();
  const labelStyle = [styles.body, { color: colors.muted }];

  return (
    <>
      <ScrollView
        style={{ backgroundColor: colors.bg }}
        contentContainerStyle={styles.scroll}
        keyboardShouldPersistTaps="handled"
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.container}>
          <ScreenHeader
            eyebrow="TU PRÓXIMO PASO EMPIEZA ACÁ"
            title="Mi perfil"
            subtitle="Tu experiencia, tus documentos y tus preferencias."
            right={<IconButton icon={props.dark ? 'sunny-outline' : 'moon-outline'} onPress={props.onThemeToggle} accessibilityLabel={props.dark ? 'Activar modo claro' : 'Activar modo oscuro'} />}
          />

          {props.demo && (
            <View style={[styles.notice, { backgroundColor: colors.primarySoft }]}>
              <Ionicons name="flask-outline" size={19} color={colors.primary} />
              <Text style={[styles.noticeText, { color: colors.text }]}>Estás en modo demostración. Los datos son de ejemplo y no se realizan envíos.</Text>
            </View>
          )}
          {!!error && (
            <View style={[styles.notice, { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.danger }]} accessibilityRole="alert">
              <Ionicons name="alert-circle-outline" size={20} color={colors.danger} />
              <Text style={[styles.noticeText, { color: colors.danger }]}>{error}</Text>
            </View>
          )}

          <View style={[styles.columns, wide && styles.columnsWide]}>
            <View style={[styles.column, wide && styles.mainColumn]}>
              <Card>
                <View style={styles.identity}>
                  <View style={[styles.avatar, { backgroundColor: colors.primarySoft }]}>
                    {props.photoUrl ? (
                      <Image source={{ uri: props.photoUrl }} style={styles.avatarImage} accessibilityLabel="Tu fotografía de perfil" />
                    ) : initial ? (
                      <Text style={[styles.initials, { color: colors.primary }]}>{initial}</Text>
                    ) : (
                      <Ionicons name="person-outline" size={32} color={colors.primary} />
                    )}
                  </View>
                  <View style={styles.identityText}>
                    <Text style={[styles.identityName, { color: colors.text }]}>{draft.full_name || 'Tu perfil profesional'}</Text>
                    <Text style={labelStyle}>{draft.city || 'Agregá tu ciudad de residencia'}</Text>
                    <View style={styles.badgeRow}><Badge label="Perfil privado" tone="neutral" icon="lock-closed-outline" /></View>
                  </View>
                </View>
                <View style={styles.photoButton}>
                  <Button label={props.photoUrl ? 'Cambiar fotografía' : 'Agregar fotografía'} icon="camera-outline" variant="secondary" onPress={() => { void run('photo', props.onPhoto); }} disabled={disabled} loading={working === 'photo'} />
                </View>
                <Divider />
                <SectionHeader title="Información personal" subtitle="Contale a la IA quién sos y qué sabés hacer." />
                <View style={styles.fields}>
                  <Field label="Nombre completo" value={draft.full_name} onChangeText={full_name => update({ full_name })} placeholder="Tu nombre y apellido" editable={!disabled} />
                  <Field label="Ciudad de residencia" value={draft.city} onChangeText={city => update({ city })} placeholder="Por ejemplo, Rincón de los Sauces" editable={!disabled} />
                  <Field label="Descripción profesional" value={draft.headline} onChangeText={headline => update({ headline })} placeholder="Tu oficio, habilidades y el tipo de trabajo que buscás" multiline editable={!disabled} />
                </View>
              </Card>

              <Card>
                <SectionHeader title="Experiencia laboral" subtitle="Sumá los trabajos que reflejan tu recorrido." action={<IconButton icon="add-outline" accessibilityLabel="Agregar experiencia laboral" disabled={disabled} onPress={() => update({ experiences: [...draft.experiences, { id: makeId(), company: '', role: '', description: '', start_date: '', end_date: '' }] })} />} />
                {draft.experiences.length === 0 ? (
                  <EmptyState icon="briefcase-outline" title="Tu experiencia cuenta" description="Agregá tu primer trabajo, actividad independiente o experiencia relevante." />
                ) : draft.experiences.map((experience, index) => (
                  <View key={experience.id} style={[styles.entry, { borderColor: colors.border, backgroundColor: colors.surfaceAlt }]}>
                    <View style={styles.entryHeader}>
                      <Text style={[styles.entryTitle, { color: colors.text }]}>Experiencia {index + 1}</Text>
                      <IconButton icon="close-outline" accessibilityLabel={`Eliminar experiencia ${index + 1}`} disabled={disabled} onPress={() => update({ experiences: draft.experiences.filter(item => item.id !== experience.id) })} />
                    </View>
                    <Field label="Puesto o actividad" value={experience.role} editable={!disabled} onChangeText={role => update({ experiences: draft.experiences.map(item => item.id === experience.id ? { ...item, role } : item) })} placeholder="Por ejemplo, chofer de reparto" />
                    <Field label="Empresa" value={experience.company} editable={!disabled} onChangeText={company => update({ experiences: draft.experiences.map(item => item.id === experience.id ? { ...item, company } : item) })} placeholder="Nombre de la empresa" />
                    <View style={styles.dateRow}>
                      <View style={styles.dateField}><Field label="Inicio" value={experience.start_date || ''} editable={!disabled} onChangeText={start_date => update({ experiences: draft.experiences.map(item => item.id === experience.id ? { ...item, start_date } : item) })} placeholder="AAAA-MM-DD" /></View>
                      <View style={styles.dateField}><Field label="Finalización" value={experience.end_date || ''} editable={!disabled} onChangeText={end_date => update({ experiences: draft.experiences.map(item => item.id === experience.id ? { ...item, end_date: end_date || null } : item) })} placeholder="Vacío si es actual" /></View>
                    </View>
                    <Field label="Tareas y logros" value={experience.description} editable={!disabled} onChangeText={description => update({ experiences: draft.experiences.map(item => item.id === experience.id ? { ...item, description } : item) })} placeholder="Describí tus responsabilidades" multiline />
                  </View>
                ))}
              </Card>

              <Card>
                <SectionHeader title="Licencias y formación" subtitle="Cursos, certificaciones y habilitaciones." action={<IconButton icon="add-outline" accessibilityLabel="Agregar licencia o formación" disabled={disabled} onPress={() => update({ credentials: [...draft.credentials, { id: makeId(), name: '', issuer: '', kind: 'course' }] })} />} />
                {draft.credentials.length === 0 ? (
                  <EmptyState icon="ribbon-outline" title="Mostrá tus conocimientos" description="Agregá tus cursos y licencias para encontrar oportunidades compatibles." />
                ) : draft.credentials.map((credential, index) => (
                  <View key={credential.id} style={[styles.entry, { borderColor: colors.border, backgroundColor: colors.surfaceAlt }]}>
                    <View style={styles.entryHeader}>
                      <Text style={[styles.entryTitle, { color: colors.text }]}>Formación {index + 1}</Text>
                      <IconButton icon="close-outline" accessibilityLabel={`Eliminar formación ${index + 1}`} disabled={disabled} onPress={() => update({ credentials: draft.credentials.filter(item => item.id !== credential.id) })} />
                    </View>
                    <View style={styles.kindRow}>
                      {([
                        ['course', 'Curso'], ['license', 'Licencia'], ['certification', 'Certificación'],
                      ] as const).map(([kind, label]) => (
                        <Button key={kind} label={label} variant={credential.kind === kind ? 'primary' : 'secondary'} disabled={disabled} onPress={() => update({ credentials: draft.credentials.map(item => item.id === credential.id ? { ...item, kind } : item) })} />
                      ))}
                    </View>
                    <Field label="Nombre" value={credential.name} editable={!disabled} onChangeText={name => update({ credentials: draft.credentials.map(item => item.id === credential.id ? { ...item, name } : item) })} placeholder="Por ejemplo, licencia de conducir profesional" />
                    <Field label="Institución o entidad" value={credential.issuer} editable={!disabled} onChangeText={issuer => update({ credentials: draft.credentials.map(item => item.id === credential.id ? { ...item, issuer } : item) })} placeholder="Entidad que la emitió" />
                  </View>
                ))}
              </Card>

              <Card>
                <SectionHeader title="Referencias" subtitle="Contactos que pueden respaldar tu experiencia." action={<IconButton icon="add-outline" accessibilityLabel="Agregar referencia" disabled={disabled} onPress={() => update({ references: [...draft.references, { id: makeId(), full_name: '', relationship: '', contact: '', consent_to_contact: false }] })} />} />
                {draft.references.length === 0 ? (
                  <EmptyState icon="people-outline" title="Una buena referencia ayuda" description="Compartí datos de contacto solo con el permiso de esa persona." />
                ) : draft.references.map((reference, index) => (
                  <View key={reference.id} style={[styles.entry, { borderColor: colors.border, backgroundColor: colors.surfaceAlt }]}>
                    <View style={styles.entryHeader}>
                      <Text style={[styles.entryTitle, { color: colors.text }]}>Referencia {index + 1}</Text>
                      <IconButton icon="close-outline" accessibilityLabel={`Eliminar referencia ${index + 1}`} disabled={disabled} onPress={() => update({ references: draft.references.filter(item => item.id !== reference.id) })} />
                    </View>
                    <Field label="Nombre completo" value={reference.full_name} editable={!disabled} onChangeText={full_name => update({ references: draft.references.map(item => item.id === reference.id ? { ...item, full_name } : item) })} placeholder="Nombre de la persona" />
                    <Field label="Relación profesional" value={reference.relationship} editable={!disabled} onChangeText={relationship => update({ references: draft.references.map(item => item.id === reference.id ? { ...item, relationship } : item) })} placeholder="Por ejemplo, supervisor anterior" />
                    <Field label="Correo o teléfono" value={reference.contact} editable={!disabled} onChangeText={contact => update({ references: draft.references.map(item => item.id === reference.id ? { ...item, contact } : item) })} placeholder="Datos de contacto" />
                    <View style={styles.preferenceRow}>
                      <Text style={[styles.preferenceText, { color: colors.muted }]}>Tengo su permiso para compartir estos datos.</Text>
                      <Switch value={reference.consent_to_contact} disabled={disabled} accessibilityLabel={`Permiso de contacto de referencia ${index + 1}`} onValueChange={consent_to_contact => update({ references: draft.references.map(item => item.id === reference.id ? { ...item, consent_to_contact } : item) })} trackColor={{ false: colors.border, true: colors.primary }} thumbColor={colors.surface} />
                    </View>
                  </View>
                ))}
                <Divider />
                <View style={styles.saveRow}>
                  <Text style={[styles.saveHint, { color: saved ? colors.primary : colors.muted }]}>{saved ? 'Perfil guardado' : dirty ? 'Tenés cambios sin guardar' : 'Tu información está actualizada'}</Text>
                  <Button label="Guardar perfil" icon="checkmark-outline" onPress={() => { void save(); }} disabled={disabled || !dirty} loading={working === 'save'} />
                </View>
              </Card>
            </View>

            <View style={[styles.column, wide && styles.sideColumn]}>
              <Card>
                <SectionHeader title="Mis currículums" subtitle="Una versión para cada oportunidad." />
                <Button label="Subir currículum" icon="cloud-upload-outline" onPress={() => { void run('upload', props.onUpload); }} disabled={disabled} loading={working === 'upload'} />
                <Text style={[styles.uploadHint, { color: colors.muted }]}>PDF o DOCX · Almacenamiento privado</Text>
                {props.resumes.length === 0 ? (
                  <EmptyState icon="document-text-outline" title="Tu próximo trabajo empieza con tu CV" description="Subí un archivo para que la IA pueda ayudarte a completar tu perfil." />
                ) : props.resumes.map(resume => (
                  <View key={resume.id} style={[styles.resume, { borderColor: colors.border }]}>
                    <View style={styles.resumeHeading}>
                      <View style={[styles.fileIcon, { backgroundColor: colors.primarySoft }]}><Ionicons name="document-text-outline" size={23} color={colors.primary} /></View>
                      <View style={styles.resumeText}>
                        <Text style={[styles.entryTitle, { color: colors.text }]} numberOfLines={2}>{resume.name}</Text>
                        <Text style={[styles.fileMeta, { color: colors.muted }]} numberOfLines={1}>{resume.file_name}</Text>
                        <Text style={[styles.fileMeta, { color: colors.muted }]}>{fileSize(resume.size_bytes)} · {new Date(resume.created_at).toLocaleDateString('es-AR')}</Text>
                      </View>
                    </View>
                    <View style={styles.badgeRow}>
                      {resume.is_default && <Badge label="Principal" tone="success" icon="checkmark-circle-outline" />}
                      {resume.demo && <Badge label="Demostración" tone="warning" />}
                    </View>
                    <View style={styles.resumeActions}>
                      <Button label="Ver" variant="secondary" icon="open-outline" disabled={disabled} onPress={() => { void run(`open-${resume.id}`, () => props.onOpenResume(resume.id)); }} />
                      <Button label="Extraer datos" variant="secondary" icon="sparkles-outline" disabled={disabled} loading={working === `extract-${resume.id}`} onPress={() => { void run(`extract-${resume.id}`, () => props.onExtract(resume.id)); }} />
                      <IconButton icon="trash-outline" accessibilityLabel={`Eliminar ${resume.name}`} disabled={disabled} onPress={() => removeResume(resume)} />
                    </View>
                    {!resume.is_default && props.onMakeDefault && <Button label="Usar como principal" variant="ghost" disabled={disabled} onPress={() => { void run(`default-${resume.id}`, () => props.onMakeDefault!(resume.id)); }} />}
                  </View>
                ))}
                <View style={[styles.helper, { backgroundColor: colors.surfaceAlt }]}>
                  <Ionicons name="sparkles-outline" size={18} color={colors.primary} />
                  <Text style={[styles.helperText, { color: colors.muted }]}>La IA extrae información presente en tu CV. Revisá los datos antes de guardarlos.</Text>
                </View>
              </Card>

              <Card>
                <SectionHeader title="Tu correo" subtitle="Postulaciones desde tu propia cuenta." />
                {connectedMail.length ? connectedMail.map(account => <View key={account.id} style={styles.accountEmail}><Ionicons name="mail-outline" size={23} color={colors.primary} /><Text style={[styles.email, { color: colors.text }]}>{account.email}</Text></View>) : <Text style={[styles.integrationText, { color: colors.muted }]}>Vinculá la cuenta desde la que querés enviar tu currículum.</Text>}
                <Badge label={connectedMail.length ? 'Correo vinculado' : 'Sin correo vinculado'} tone={connectedMail.length ? 'success' : 'warning'} />
                <Text style={[styles.integrationText, { color: colors.muted }]}>El envío se realiza desde tu cuenta mediante una conexión segura. Autorizá los envíos diarios para cada búsqueda y después se ejecutarán automáticamente mientras el permiso esté vigente.</Text>
                <Button label={connectedMail.length ? 'Vincular otra cuenta' : 'Conectar correo'} icon="link-outline" variant="secondary" disabled={disabled} loading={working === 'mail'} onPress={() => { void run('mail', props.onConnectMail); }} />
              </Card>

              <Card>
                <SectionHeader title="Preferencias y cuenta" />
                <Text style={[styles.entryTitle, { color: colors.text }]}>Tema de la aplicación</Text>
                <Text style={[styles.themeHint, { color: colors.muted }]}>Elegí la apariencia. Tu preferencia se guarda en este dispositivo.</Text>
                <View style={styles.themeChoices}>
                  {([
                    ['light', 'Claro', 'sunny-outline'],
                    ['dark', 'Oscuro', 'moon-outline'],
                    ['system', 'Según el dispositivo', 'phone-portrait-outline'],
                  ] as const).map(([choice, label, icon]) => (
                    <Pressable
                      key={choice}
                      accessibilityRole="radio"
                      accessibilityLabel={label}
                      accessibilityState={{ checked: preference === choice }}
                      onPress={() => setPreference(choice)}
                      style={({ pressed }) => [
                        styles.themeChoice,
                        {
                          backgroundColor: preference === choice ? colors.primarySoft : colors.surfaceAlt,
                          borderColor: preference === choice ? colors.primary : colors.border,
                          opacity: pressed ? 0.75 : 1,
                        },
                      ]}
                    >
                      <Ionicons name={icon} size={20} color={preference === choice ? colors.primary : colors.text} />
                      <Text style={[styles.themeChoiceLabel, { color: colors.text }]}>{label}</Text>
                      <Ionicons name={preference === choice ? 'radio-button-on' : 'radio-button-off'} size={21} color={preference === choice ? colors.primary : colors.muted} />
                    </Pressable>
                  ))}
                </View>
                <Divider />
                <View style={styles.helper}>
                  <Ionicons name="shield-checkmark-outline" size={21} color={colors.primary} />
                  <Text style={[styles.helperText, { color: colors.muted }]}>Tus documentos y datos profesionales están vinculados a tu cuenta. Podés eliminar tu información cuando lo necesites.</Text>
                </View>
                <Button label="Cerrar sesión" icon="log-out-outline" variant="secondary" onPress={props.onSignOut} disabled={disabled} />
                <Button label="Eliminar cuenta y datos" icon="trash-outline" variant="ghost" disabled={disabled} onPress={() => { setDeleteText(''); setDeleteOpen(true); }} />
              </Card>
            </View>
          </View>
        </View>
      </ScrollView>

      <Modal visible={deleteOpen} transparent animationType="fade" onRequestClose={() => { if (!disabled) setDeleteOpen(false); }}>
        <View style={styles.modalBackdrop}>
          <View style={[styles.modalCard, { backgroundColor: colors.surface }]}>
            <View style={styles.entryHeader}>
              <Text style={[styles.modalTitle, { color: colors.text }]}>Eliminar tu cuenta</Text>
              <IconButton icon="close-outline" accessibilityLabel="Cancelar eliminación de cuenta" disabled={disabled} onPress={() => setDeleteOpen(false)} />
            </View>
            <Text style={[styles.integrationText, { color: colors.muted }]}>Se eliminarán tu perfil, documentos, búsquedas e historial. Esta acción no se puede deshacer.</Text>
            <Field label="Escribí ELIMINAR para confirmar" value={deleteText} onChangeText={setDeleteText} placeholder="ELIMINAR" editable={!disabled} />
            <View style={styles.modalActions}>
              <Button label="Cancelar" variant="secondary" disabled={disabled} onPress={() => setDeleteOpen(false)} />
              <Button label="Eliminar cuenta" variant="danger" loading={working === 'account-delete'} disabled={disabled || deleteText !== 'ELIMINAR'} onPress={() => { void run('account-delete', async () => { await props.onDeleteAccount(); setDeleteOpen(false); }); }} />
            </View>
          </View>
        </View>
      </Modal>
    </>
  );
}

const styles = StyleSheet.create({
  scroll: { paddingHorizontal: 20, paddingTop: 26, paddingBottom: 40 },
  container: { width: '100%', maxWidth: 1160, alignSelf: 'center', gap: 22 },
  columns: { gap: 20 },
  columnsWide: { flexDirection: 'row', alignItems: 'flex-start' },
  column: { gap: 20, minWidth: 0 },
  mainColumn: { flex: 1.5 },
  sideColumn: { flex: 1 },
  notice: { borderRadius: 14, flexDirection: 'row', alignItems: 'center', padding: 14, gap: 10 },
  noticeText: { fontSize: 13, lineHeight: 20, flex: 1 },
  identity: { flexDirection: 'row', alignItems: 'center', gap: 16 },
  avatar: { width: 76, height: 76, borderRadius: 26, alignItems: 'center', justifyContent: 'center', overflow: 'hidden' },
  avatarImage: { width: 76, height: 76 },
  initials: { fontSize: 26, fontWeight: '700' },
  identityText: { flex: 1, gap: 5 },
  identityName: { fontSize: 21, fontWeight: '700', letterSpacing: -0.5 },
  body: { fontSize: 13, lineHeight: 20 },
  photoButton: { alignItems: 'flex-start', marginTop: 14, marginBottom: 8 },
  fields: { gap: 14 },
  badgeRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 4 },
  entry: { borderWidth: 1, borderRadius: 14, padding: 14, marginTop: 12, gap: 12 },
  entryHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 10 },
  entryTitle: { fontSize: 14, fontWeight: '600', lineHeight: 21, flexShrink: 1 },
  dateRow: { flexDirection: 'row', gap: 12 },
  dateField: { flex: 1 },
  kindRow: { flexDirection: 'row', gap: 6, flexWrap: 'wrap' },
  preferenceRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  preferenceText: { flex: 1, fontSize: 12, lineHeight: 19 },
  themeHint: { fontSize: 12, lineHeight: 19, marginTop: 5, marginBottom: 12 },
  themeChoices: { gap: 8 },
  themeChoice: { minHeight: 48, borderWidth: 1, borderRadius: 12, paddingHorizontal: 13, flexDirection: 'row', alignItems: 'center', gap: 10 },
  themeChoiceLabel: { flex: 1, fontSize: 13, fontWeight: '600' },
  saveRow: { gap: 12 },
  saveHint: { fontSize: 12, lineHeight: 18 },
  uploadHint: { fontSize: 11, marginTop: 8, marginBottom: 6, textAlign: 'center' },
  resume: { borderWidth: 1, borderRadius: 14, padding: 14, gap: 10, marginTop: 14 },
  resumeHeading: { flexDirection: 'row', gap: 11, alignItems: 'flex-start' },
  fileIcon: { width: 42, height: 46, borderRadius: 11, alignItems: 'center', justifyContent: 'center' },
  resumeText: { flex: 1, gap: 2 },
  fileMeta: { fontSize: 11, lineHeight: 18 },
  resumeActions: { flexDirection: 'row', alignItems: 'center', gap: 7, flexWrap: 'wrap' },
  helper: { flexDirection: 'row', gap: 10, padding: 12, borderRadius: 12, marginTop: 12, marginBottom: 12 },
  helperText: { flex: 1, fontSize: 12, lineHeight: 19 },
  accountEmail: { flexDirection: 'row', gap: 11, alignItems: 'center', marginBottom: 14 },
  email: { flex: 1, fontSize: 13, fontWeight: '600', lineHeight: 20 },
  integrationText: { fontSize: 13, lineHeight: 21, marginVertical: 14 },
  modalBackdrop: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24, backgroundColor: 'rgba(8, 19, 32, 0.65)' },
  modalCard: { width: '100%', maxWidth: 460, padding: 24, borderRadius: 22, gap: 8 },
  modalTitle: { fontSize: 20, fontWeight: '700', flex: 1 },
  modalActions: { flexDirection: 'row', gap: 10, justifyContent: 'flex-end', flexWrap: 'wrap', marginTop: 16 },
});

export { ProfileScreen };
