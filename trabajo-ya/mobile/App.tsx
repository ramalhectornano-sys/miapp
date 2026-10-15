import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Linking, Modal, Platform, Pressable, ScrollView, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { SafeAreaProvider, SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { StatusBar } from 'expo-status-bar';
import * as DocumentPicker from 'expo-document-picker';
import * as ImagePicker from 'expo-image-picker';
import * as WebBrowser from 'expo-web-browser';
import type { Session } from '@supabase/supabase-js';
import { ThemeProvider, useTheme } from './src/theme/theme';
import { BrandMark, Button, IconButton } from './src/components/ui';
import ConsentModal from './src/components/ConsentModal';
import JobResultsModal from './src/components/JobResultsModal';
import WebHistoryModal from './src/components/WebHistoryModal';
import AssistantScreen from './src/screens/AssistantScreen';
import ApplicationsScreen from './src/screens/ApplicationsScreen';
import SearchesScreen from './src/screens/SearchesScreen';
import ProfileScreen from './src/screens/ProfileScreen';
import AuthScreen from './src/screens/AuthScreen';
import { initialDemoState, demoChat, demoSearch } from './src/state/demo';
import { config } from './src/config';
import { getSession, observeAuthRefresh, requestEmailCode, verifyEmailCode, signOut, supabase, SUPABASE_CONFIGURED, authLinkHandler } from './src/services/supabase';
import { observeAuthLinkEvents } from './src/services/authLinks';
import { chat, createSearch, updateSearch, runSearch, extractResume, startGoogleOAuth, sendApplication, stopApplicationFollowups, deleteAccount, getRuns, getSearchResults, getWebHistory, resolveLocations, type SearchRun } from './src/services/backend';
import { loadState, saveProfile, uploadResume, deleteResume, getResumeUrl, uploadPhoto, getPhotoUrl, makeDefaultResume } from './src/services/data';
import { sameSearchConfiguration } from './src/state/geography';
import type { AppState, ChatMessage, FoundJob, JobSearch, Notice, Profile, ResearchEvent, Resume, SearchProposal, Tab } from './src/types';

const navigation: { key: Tab; label: string; short: string; icon: React.ComponentProps<typeof Ionicons>['name'] }[] = [
  { key: 'assistant', label: 'Asistente IA', short: 'Asistente IA', icon: 'chatbubble-ellipses-outline' },
  { key: 'applications', label: 'Mis postulaciones', short: 'Postulaciones', icon: 'briefcase-outline' },
  { key: 'searches', label: 'Búsquedas automáticas', short: 'Búsquedas', icon: 'calendar-outline' },
  { key: 'profile', label: 'Mi perfil', short: 'Mi perfil', icon: 'person-outline' },
];

const emptyState = (): AppState => ({ profile: { full_name: '', city: '', headline: '', photo_path: null, experiences: [], credentials: [], references: [] }, resumes: [], searches: [], applications: [], messages: [] });
const uniqueId = () => `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
const errorText = (caught: unknown) => caught instanceof Error ? caught.message : 'No pudimos completar la operación. Intentá nuevamente.';
const sameSearch = sameSearchConfiguration;

function Workspace() {
  const { colors, dark, toggle, ready: themeReady } = useTheme();
  const { width } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const desktop = width >= 980;
  const [demo, setDemo] = useState(config.demo);
  const [session, setSession] = useState<Session | null>(null);
  const [data, setData] = useState<AppState>(() => config.demo ? initialDemoState() : emptyState());
  const [tab, setTab] = useState<Tab>('assistant');
  const [permissionsId, setPermissionsId] = useState<string | null>(null);
  const [executionHistory, setExecutionHistory] = useState<{ name: string; runs: SearchRun[] } | null>(null);
  const [jobResults, setJobResults] = useState<{ name: string; jobs: FoundJob[] } | null>(null);
  const [webHistory, setWebHistory] = useState<{ name: string; events: ResearchEvent[] } | null>(null);
  const [loading, setLoading] = useState(!config.demo && SUPABASE_CONFIGURED);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [photoUrl, setPhotoUrl] = useState<string | undefined>();
  const [extraction, setExtraction] = useState<{ text: string; message: string } | null>(null);
  const localDocuments = useRef(new Map<string, string>());
  const operationLock = useRef(false);
  const mounted = useRef(true);
  const currentScope = useRef({ demo, userId: session?.user.id });
  currentScope.current = { demo, userId: session?.user.id };

  useEffect(() => {
    mounted.current = true;
    if (!supabase) { setLoading(false); return () => { mounted.current = false; }; }
    const stopRefresh = observeAuthRefresh();
    let authRevision = 0;
    const subscription = supabase.auth.onAuthStateChange((_event, nextSession) => {
      if (!mounted.current) return;
      authRevision++;
      if (currentScope.current.userId !== nextSession?.user.id && !currentScope.current.demo) {
        setData(emptyState()); setPhotoUrl(undefined); setExtraction(null); setPermissionsId(null); setExecutionHistory(null); setJobResults(null); setWebHistory(null); setLoading(!!nextSession);
      }
      currentScope.current = { ...currentScope.current, userId: nextSession?.user.id };
      if (!nextSession) setLoading(false);
      setSession(nextSession);
    });
    const initialRevision = authRevision;
    void getSession().then(nextSession => { if (mounted.current && authRevision === initialRevision) { setSession(nextSession); if (!nextSession) setLoading(false); } }).catch(caught => { if (mounted.current && authRevision === initialRevision) { setNotice({ text: errorText(caught), kind: 'error' }); setLoading(false); } });
    const stopLinks = config.demo || Platform.OS === 'web' ? () => {} : observeAuthLinkEvents(Linking, authLinkHandler,
      () => { if (mounted.current) setNotice({ text: 'Correo verificado. Ya podés usar tu cuenta.', kind: 'success' }); },
      text => { if (mounted.current) setNotice({ text, kind: 'error' }); });
    return () => { mounted.current = false; stopLinks(); subscription.data.subscription.unsubscribe(); stopRefresh(); };
  }, []);

  const refresh = useCallback(async () => {
    if (demo || !session) return;
    const userId = session.user.id;
    const state = await loadState();
    if (!mounted.current || currentScope.current.demo || currentScope.current.userId !== userId) return;
    setData({ ...state, messages: state.messages.map(item => ({ ...item, saved: !!item.proposal && state.searches.some(search => sameSearch(search, item.proposal!)) })) });
    if (state.profile.photo_path) {
      try { const url = await getPhotoUrl(state.profile.photo_path); if (!currentScope.current.demo && currentScope.current.userId === userId) setPhotoUrl(url); }
      catch { if (!currentScope.current.demo && currentScope.current.userId === userId) setPhotoUrl(undefined); }
    } else setPhotoUrl(undefined);
  }, [demo, session?.user.id]);

  useEffect(() => {
    if (demo || !session) return;
    let cancelled = false;
    setLoading(true);
    void refresh().catch(caught => { if (!cancelled) setNotice({ text: errorText(caught), kind: 'error' }); }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [refresh]);

  const stillCurrent = () => mounted.current && currentScope.current.demo === demo && currentScope.current.userId === session?.user.id;
  const commitData: typeof setData = update => { if (stillCurrent()) setData(update); };
  const commitPhotoUrl: typeof setPhotoUrl = update => { if (stillCurrent()) setPhotoUrl(update); };

  const perform = async <T,>(action: () => Promise<T>): Promise<T> => {
    if (operationLock.current) throw new Error('Esperá a que termine la operación anterior.');
    operationLock.current = true;
    setBusy(true);
    setNotice(null);
    try { return await action(); }
    catch (caught) { if (stillCurrent()) setNotice({ text: errorText(caught), kind: 'error' }); throw caught; }
    finally { operationLock.current = false; setBusy(false); }
  };
  // These callbacks are invoked by buttons that do not await failures.
  const safely = async (action: () => Promise<unknown>) => { try { await perform(action); } catch { /* The notice contains the actual error. */ } };
  const message = (text: string, kind: Notice['kind'] = 'success') => setNotice({ text, kind });

  const enterDemo = () => { setDemo(true); setData(initialDemoState()); setTab('assistant'); setPhotoUrl(undefined); localDocuments.current.clear(); setNotice(null); setPermissionsId(null); setExecutionHistory(null); setJobResults(null); setWebHistory(null); setLoading(false); };
  const logout = async () => {
    if (!demo || session) await signOut();
    setDemo(false); setSession(null); setData(emptyState()); setPhotoUrl(undefined); localDocuments.current.clear(); setTab('assistant'); setPermissionsId(null); setExecutionHistory(null); setJobResults(null); setWebHistory(null);
    message('Sesión cerrada.', 'info');
  };

  const sendChat = (text: string) => perform(async () => {
    const created_at = new Date().toISOString();
    const response = demo ? demoChat(text) : await chat(text, data.messages.slice(-12).map(({ role, content }) => ({ role, content })));
    const messages: ChatMessage[] = [
      { id: uniqueId(), role: 'user', content: text, created_at, demo },
      { id: uniqueId(), role: 'assistant', content: response.reply, proposal: response.proposal || undefined, saved: !!response.proposal && data.searches.some(search => sameSearch(search, response.proposal!)), created_at, demo: demo || ('mode' in response && response.mode === 'demo') },
    ];
    commitData(current => ({ ...current, messages: [...current.messages, ...messages] }));
  });

  const saveSearch = async (proposal: SearchProposal): Promise<JobSearch> => {
    const requested: SearchProposal = { ...proposal, resume_id: proposal.resume_id || data.resumes.find(resume => resume.is_default)?.id };
    const existing = data.searches.find(search => sameSearch(search, requested));
    if (existing) { message('Esta configuración ya está guardada. Podés verla en Búsquedas automáticas.', 'info'); if (proposal.mode === 'automatic' && !demo) setPermissionsId(existing.id); return existing; }
    if (demo) {
      const search = demoSearch(requested);
      commitData(current => ({ ...current, searches: [...current.searches, search] }));
      message('Configuración de demostración guardada en esta sesión. No se ejecutó ninguna búsqueda ni se autorizaron envíos reales.', 'info');
      return search;
    }
    const result = await createSearch(requested);
    commitData(current => ({ ...current, searches: [result.search, ...current.searches] }));
    message(result.message, result.automatic_authorization_required ? 'info' : 'success');
    if (result.automatic_authorization_required && stillCurrent()) setTimeout(() => { if (stillCurrent()) setPermissionsId(result.search.id); }, 0);
    return result.search;
  };

  const saveProfileAction = (profile: Profile) => perform(async () => {
    const saved = demo ? profile : await saveProfile(profile);
    commitData(current => ({ ...current, profile: saved }));
    message(demo ? 'Perfil de demostración actualizado en esta sesión. No se guardó en el servidor.' : 'Perfil guardado en tu cuenta privada.', demo ? 'info' : 'success');
  });

  const upload = () => perform(async () => {
    const result = await DocumentPicker.getDocumentAsync({ type: ['application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'], copyToCacheDirectory: true, multiple: false });
    if (result.canceled) return;
    const asset = result.assets[0];
    if (!/\.(pdf|docx)$/i.test(asset.name)) throw new Error('Elegí un currículum PDF o DOCX.');
    if (asset.size && asset.size > 10 * 1024 * 1024) throw new Error('El archivo debe pesar como máximo 10 MB.');
    let resume: Resume;
    if (demo) {
      resume = { id: uniqueId(), name: asset.name.replace(/\.(pdf|docx)$/i, ''), file_name: asset.name, storage_path: '', mime_type: asset.mimeType || (/\.pdf$/i.test(asset.name) ? 'application/pdf' : 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'), size_bytes: asset.size || 0, created_at: new Date().toISOString(), is_default: data.resumes.length === 0, demo: true };
      localDocuments.current.set(resume.id, asset.uri);
    } else resume = await uploadResume(asset);
    commitData(current => ({ ...current, resumes: [resume, ...current.resumes.map(item => resume.is_default ? { ...item, is_default: false } : item)] }));
    message(demo ? 'Archivo seleccionado para esta demostración. No se subió al servidor; se conserva una referencia local durante esta sesión.' : 'Currículum guardado en almacenamiento privado.', demo ? 'info' : 'success');
  });

  const changePhoto = () => perform(async () => {
    const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!permission.granted) throw new Error('Permití el acceso a tus fotos para elegir una imagen.');
    const result = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images'], allowsEditing: true, aspect: [1, 1], quality: .8 });
    if (result.canceled) return;
    const asset = result.assets[0];
    if (demo) { commitPhotoUrl(asset.uri); message('Foto local para esta sesión de demostración. No se subió al servidor.', 'info'); return; }
    const uploaded = await uploadPhoto({ uri: asset.uri, name: asset.fileName || 'foto.jpg', mimeType: asset.mimeType || 'image/jpeg', size: asset.fileSize, file: asset.file });
    commitPhotoUrl(uploaded.url); commitData(current => ({ ...current, profile: { ...current.profile, photo_path: uploaded.path } })); message('Foto actualizada en tu perfil privado.');
  });

  const openResume = (id: string) => perform(async () => {
    const resume = data.resumes.find(item => item.id === id);
    if (!resume) throw new Error('No encontramos ese currículum.');
    if (demo) {
      const uri = localDocuments.current.get(id);
      if (!uri) { message('Este CV es un ejemplo de demostración y no tiene un documento adjunto.', 'info'); return; }
      if (Platform.OS !== 'web') { message('El archivo fue seleccionado localmente. La vista de documentos privados está disponible al conectar tu cuenta real.', 'info'); return; }
      await Linking.openURL(uri);
    } else await WebBrowser.openBrowserAsync(await getResumeUrl(resume));
  });

  const removeResume = (id: string) => perform(async () => {
    const resume = data.resumes.find(item => item.id === id);
    if (!resume) throw new Error('No encontramos ese currículum.');
    if (!demo) await deleteResume(resume);
    localDocuments.current.delete(id);
    commitData(current => ({ ...current, resumes: current.resumes.filter(item => item.id !== id) }));
    message(demo ? 'Currículum retirado de esta demostración.' : 'Currículum eliminado de tu cuenta.');
  });

  const extract = (id: string) => perform(async () => {
    if (demo) { message('La extracción real de PDF y DOCX requiere tu cuenta y el backend configurado. No se leyó ni se inventó información del archivo.', 'info'); return; }
    const result = await extractResume(id);
    if (stillCurrent()) setExtraction({ text: result.text, message: result.message });
  });

  const connectMail = () => perform(async () => {
    if (demo) { message('OAuth está deshabilitado en la demostración. Conectá las integraciones del servidor para vincular una cuenta real.', 'info'); return; }
    const result = await startGoogleOAuth();
    await WebBrowser.openBrowserAsync(result.authorization_url);
    message('Terminá la autorización en el navegador. La conexión no autoriza envíos automáticos.', 'info');
  });

  const deleteUser = () => perform(async () => {
    if (demo) { commitData(emptyState()); localDocuments.current.clear(); commitPhotoUrl(undefined); message('Los datos de esta sesión de demostración se borraron. No se eliminó ninguna cuenta real.', 'info'); return; }
    const result = await deleteAccount();
    if (!result.deleted) throw new Error('El servidor no confirmó la eliminación de tu cuenta.');
    try { await signOut(); } catch { /* The backend already confirmed the deletion. */ }
    setSession(null); commitData(emptyState()); commitPhotoUrl(undefined); message(result.message);
  });

  const stopFollowups = (id: string) => perform(async () => {
    if (demo) throw new Error('La demostración no modifica autorizaciones ni envíos reales.');
    const result = await stopApplicationFollowups(id);
    if (!result.stopped) throw new Error('El servidor no confirmó que se detuvieron los reenvíos.');
    const address = result.recipient_email.trim().toLowerCase();
    commitData(current => ({ ...current, applications: current.applications.map(item => item.recipient_email.trim().toLowerCase() === address ? { ...item, followups_stopped: true, followups_stopped_at: result.stopped_at, followups_stop_reason: result.reason } : item) }));
    message(result.message);
  });

  const resolveLocation: typeof resolveLocations = async location => {
    if (demo) throw new Error('La demostración no consulta ubicaciones reales.');
    const result = await resolveLocations(location);
    if (!stillCurrent()) throw new Error('La cuenta cambió durante la consulta. Volvé a comprobar la ubicación.');
    return result;
  };

  const refreshButton = () => safely(async () => { if (demo) { message('Estás viendo datos de demostración. No hay operaciones del servidor para actualizar.', 'info'); return; } await refresh(); message('Información actualizada desde tu cuenta.'); });

  let screen: React.ReactNode;
  if (loading || !themeReady) screen = <View style={styles.loading}><ActivityIndicator color={colors.primary} /><Text style={{ color: colors.muted, fontSize: 12 }}>Cargando tu espacio de trabajo…</Text></View>;
  else if (!demo && !session) screen = <AuthScreen configured={SUPABASE_CONFIGURED} onDemo={config.demo ? enterDemo : undefined} onRequestCode={async (email, name) => { setNotice(null); await requestEmailCode(email, name); }} onVerifyCode={async (email, token) => { setNotice(null); const result = await verifyEmailCode(email, token); setData(emptyState()); setSession(result); }} />;
  else if (tab === 'assistant') screen = <AssistantScreen key={`assistant-${demo ? 'demo' : session?.user.id}`} onResolveLocation={resolveLocation} profile={data.profile} messages={data.messages} busy={busy} demo={demo} onSend={sendChat} onSaveProposal={(id, proposal) => safely(async () => { await saveSearch(proposal); commitData(current => ({ ...current, messages: current.messages.map(item => item.id === id ? { ...item, proposal, saved: true } : item) })); })} />;
  else if (tab === 'applications') screen = <ApplicationsScreen onStopFollowups={stopFollowups} applications={data.applications} resumes={data.resumes} busy={busy} demo={demo} onSend={id => safely(async () => { if (demo) throw new Error('El envío de correos está deshabilitado en la demostración.'); const result = await sendApplication(id); commitData(current => ({ ...current, applications: current.applications.map(item => item.id === id ? result : item) })); if (result.status === 'sent' && result.provider_message_id && result.provider_confirmed_at) message('El proveedor confirmó el envío de esta postulación.'); else message('La operación no tiene confirmación de envío. Revisá su estado y el detalle.', 'info'); })} />;
  else if (tab === 'searches') screen = <SearchesScreen key={`searches-${demo ? 'demo' : session?.user.id}`} onResolveLocation={resolveLocation} onWebHistory={search => void safely(async () => { if (demo) return; const events = await getWebHistory(search.id); if (stillCurrent()) setWebHistory({ name: search.name, events }); })} searches={data.searches} resumes={data.resumes} busy={busy} demo={demo} onPermissions={search => setPermissionsId(search.id)} onResults={search => void safely(async () => { if (demo) { message("Las ofertas reales se consultan con una búsqueda del servidor.", "info"); return; } const jobs = await getSearchResults(search.id); if (stillCurrent()) setJobResults({ name: search.name, jobs }); })} onHistory={search => void safely(async () => { if (demo) { message('Esta búsqueda es de demostración. No tiene ejecuciones reales.', 'info'); return; } const runs = await getRuns(search.id); if (stillCurrent()) setExecutionHistory({ name: search.name, runs }); })} onCreate={proposal => perform(async () => { await saveSearch(proposal); })} onToggle={search => safely(async () => { const status = search.status === 'enabled' ? 'paused' : 'enabled'; const updated = demo ? { ...search, status } as JobSearch : { ...search, ...await updateSearch(search.id, { status }) }; commitData(current => ({ ...current, searches: current.searches.map(item => item.id === search.id ? updated : item) })); message(demo ? 'Configuración de demostración actualizada. No se ejecutó ninguna tarea.' : `Búsqueda ${status === 'enabled' ? 'habilitada en la configuración; el historial confirma sus ejecuciones' : 'pausada'}.`, demo ? 'info' : 'success'); })} onRun={id => safely(async () => { if (demo) throw new Error('Las búsquedas no se ejecutan en la demostración.'); const result = await runSearch(id); message(result.message, result.status === 'completed' ? 'success' : 'info'); await refresh(); })} />;
  else screen = <ProfileScreen profile={data.profile} resumes={data.resumes} busy={busy} demo={demo} mailConnections={data.email_connections || []} email={demo ? 'Demostración · sin cuenta conectada' : session?.user.email} photoUrl={photoUrl} dark={dark} onThemeToggle={toggle} onSave={saveProfileAction} onUpload={upload} onPhoto={changePhoto} onOpenResume={openResume} onDeleteResume={removeResume} onExtract={extract} onConnectMail={connectMail} onDeleteAccount={deleteUser} onSignOut={() => void safely(logout)} onMakeDefault={id => perform(async () => { if (!demo) await makeDefaultResume(id); commitData(current => ({ ...current, resumes: current.resumes.map(item => ({ ...item, is_default: item.id === id })) })); message(demo ? 'Versión elegida para esta sesión de demostración.' : 'Currículum principal guardado en tu cuenta.', demo ? 'info' : 'success'); })} />;

  const authenticated = demo || !!session;
  const initials = data.profile.full_name.trim().split(/\s+/).filter(Boolean).slice(0, 2).map(part => part[0]).join('') || 'TY';
  return <SafeAreaView edges={['top', 'left', 'right']} style={{ flex: 1, backgroundColor: colors.bg }}>
    <StatusBar style={dark ? 'light' : 'dark'} />
    <View style={{ flex: 1, flexDirection: 'row' }}>
      {authenticated && desktop ? <View style={[styles.sidebar, { backgroundColor: colors.surface, borderRightColor: colors.border }]}>
        <View style={styles.brand}><BrandMark size={35} /><View><Text style={{ color: colors.text, fontSize: 17, fontWeight: '600', letterSpacing: -.5 }}>Trabajo <Text style={{ color: colors.primary }}>YA</Text></Text><Text style={{ color: colors.muted, fontSize: 8, letterSpacing: 1.6, marginTop: 5 }}>TU ASISTENTE DE EMPLEO</Text></View></View>
        <Text style={{ color: colors.muted, fontSize: 8, letterSpacing: 1.8, fontWeight: '600', marginTop: 46, marginBottom: 18, paddingHorizontal: 13 }}>TU ESPACIO DE TRABAJO</Text>
        <View style={{ gap: 7 }}>{navigation.map(item => <Pressable key={item.key} accessibilityRole="tab" accessibilityState={{ selected: tab === item.key }} accessibilityLabel={item.label} onPress={() => setTab(item.key)} style={({ pressed }) => [styles.sidebarItem, { backgroundColor: tab === item.key ? colors.primarySoft : pressed ? colors.bg : 'transparent' }]}><Ionicons name={item.icon} size={19} color={tab === item.key ? colors.primary : colors.muted} /><Text style={{ color: tab === item.key ? colors.primary : colors.muted, fontSize: 12, fontWeight: tab === item.key ? '600' : '400', flex: 1 }}>{item.label}</Text>{tab === item.key ? <View style={{ width: 5, height: 5, borderRadius: 3, backgroundColor: colors.primary }} /> : null}</Pressable>)}</View>
        <View style={{ flex: 1 }} />
        <View style={{ padding: 14, borderWidth: 1, borderColor: colors.border, borderRadius: 12, gap: 9, marginBottom: 24 }}><Ionicons name="shield-checkmark-outline" size={20} color={colors.primary} /><Text style={{ color: colors.text, fontSize: 11, fontWeight: '600' }}>Tu búsqueda, bajo tu control</Text><Text style={{ color: colors.muted, fontSize: 10, lineHeight: 18 }}>Tus datos son privados. Cada envío requiere autorización.</Text></View>
        <Pressable accessibilityRole="button" accessibilityLabel="Abrir mi perfil" onPress={() => setTab('profile')} style={{ flexDirection: 'row', gap: 10, alignItems: 'center', paddingTop: 18, borderTopWidth: 1, borderTopColor: colors.border }}><View style={[styles.avatar, { backgroundColor: colors.primarySoft }]}><Text style={{ color: colors.primary, fontSize: 12, fontWeight: '600' }}>{initials}</Text></View><View style={{ flex: 1 }}><Text numberOfLines={1} style={{ color: colors.text, fontSize: 11, fontWeight: '600' }}>{data.profile.full_name || 'Mi cuenta'}</Text><Text style={{ color: colors.muted, fontSize: 9, marginTop: 4 }}>{demo ? 'Espacio de demostración' : 'Perfil profesional'}</Text></View><Ionicons name="chevron-forward-outline" size={13} color={colors.muted} /></Pressable>
      </View> : null}
      <View style={{ flex: 1, minWidth: 0 }}>
        {authenticated ? <View style={[styles.header, { backgroundColor: colors.surface, borderBottomColor: colors.border, paddingHorizontal: desktop ? 34 : 18 }]}>{desktop ? <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, flex: 1 }}><Text style={{ color: colors.muted, fontSize: 10 }}>Mi espacio</Text><Ionicons name="chevron-forward-outline" size={10} color={colors.muted} /><Text style={{ color: colors.text, fontSize: 10 }}>{navigation.find(item => item.key === tab)?.label}</Text></View> : <View style={[styles.brand, { flex: 1, gap: 8 }]}><BrandMark size={29} /><View><Text style={{ color: colors.text, fontSize: 16, fontWeight: '600', letterSpacing: -.4 }}>Trabajo <Text style={{ color: colors.primary }}>YA</Text></Text><Text style={{ color: colors.muted, fontSize: 7, letterSpacing: 1.3, marginTop: 3 }}>TU ASISTENTE DE EMPLEO</Text></View></View>}<IconButton icon="refresh-outline" onPress={() => void refreshButton()} accessibilityLabel="Actualizar información" disabled={busy || loading} /><IconButton icon={dark ? 'sunny-outline' : 'moon-outline'} onPress={toggle} accessibilityLabel={dark ? 'Activar modo claro' : 'Activar modo oscuro'} />{desktop ? <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, marginLeft: 10 }}><View style={{ width: 5, height: 5, borderRadius: 4, backgroundColor: demo ? colors.warning : colors.primary }} /><Text style={{ color: colors.muted, fontSize: 9 }}>{demo ? 'Demostración' : 'Mi cuenta'}</Text></View> : null}</View> : null}
        {authenticated && demo ? <View style={[styles.demoBanner, { backgroundColor: `${colors.warning}0C`, borderBottomColor: colors.border }]}><Ionicons name="information-circle-outline" size={13} color={colors.warning} /><Text style={{ color: colors.warning, fontSize: 9, lineHeight: 15, flex: 1 }}>Modo demostración · No se ejecutan búsquedas ni se envían correos</Text></View> : null}
        {notice ? <View style={[styles.notice, { backgroundColor: notice.kind === 'error' ? `${colors.danger}12` : colors.primarySoft }]}><Ionicons name={notice.kind === 'error' ? 'alert-circle-outline' : notice.kind === 'success' ? 'checkmark-circle-outline' : 'information-circle-outline'} size={18} color={notice.kind === 'error' ? colors.danger : colors.primary} /><Text accessibilityRole="alert" style={{ color: notice.kind === 'error' ? colors.danger : colors.primary, fontSize: 11, lineHeight: 19, flex: 1 }}>{notice.text}</Text><IconButton icon="close-outline" accessibilityLabel="Cerrar aviso" onPress={() => setNotice(null)} /></View> : null}
        <View style={{ flex: 1 }}>{screen}</View>
        {authenticated && !desktop ? <View style={[styles.bottomNav, { backgroundColor: colors.surface, borderTopColor: colors.border, paddingBottom: Math.max(insets.bottom, 10) }]}>{navigation.map(item => <Pressable key={item.key} accessibilityRole="tab" accessibilityLabel={item.label} accessibilityState={{ selected: tab === item.key }} onPress={() => setTab(item.key)} style={styles.bottomItem}><View style={{ paddingVertical: 5, paddingHorizontal: 16, borderRadius: 12, backgroundColor: tab === item.key ? colors.primarySoft : 'transparent' }}><Ionicons name={item.icon} size={21} color={tab === item.key ? colors.primary : colors.muted} /></View><Text style={{ color: tab === item.key ? colors.primary : colors.muted, fontSize: width < 370 ? 8 : 9, marginTop: 5, fontWeight: tab === item.key ? '600' : '400' }}>{item.short}</Text></Pressable>)}</View> : null}
      </View>
    </View>
    <ConsentModal key={`consent-${demo ? 'demo' : session?.user.id}`} search={data.searches.find(search => search.id === permissionsId) || null} resumes={data.resumes} demo={demo} onClose={() => setPermissionsId(null)} onChanged={search => commitData(current => ({ ...current, searches: current.searches.map(item => item.id === search.id ? search : item) }))} />
    <JobResultsModal results={jobResults} onClose={() => setJobResults(null)} />
    <WebHistoryModal history={webHistory} onClose={() => setWebHistory(null)} />
    <Modal visible={!!executionHistory} transparent animationType="fade" onRequestClose={() => setExecutionHistory(null)}><View style={styles.overlay}><View style={[styles.extractionCard, { backgroundColor: colors.surface }]}><View style={{ flexDirection: 'row', alignItems: 'center' }}><View style={{ flex: 1 }}><Text style={{ color: colors.text, fontSize: 22, fontWeight: '600' }}>Historial de búsquedas</Text><Text style={{ color: colors.muted, fontSize: 12, marginTop: 8 }}>{executionHistory?.name}</Text></View><IconButton icon="close-outline" accessibilityLabel="Cerrar historial de búsquedas" onPress={() => setExecutionHistory(null)} /></View><ScrollView contentContainerStyle={{ gap: 14, paddingVertical: 20 }}>{executionHistory?.runs.length ? executionHistory.runs.map(run => <View key={run.id} style={{ padding: 16, borderWidth: 1, borderColor: colors.border, borderRadius: 12, gap: 8 }}><Text style={{ color: run.status === 'completed' ? colors.primary : run.status === 'error' ? colors.danger : colors.warning, fontSize: 13, fontWeight: '600' }}>{{ running: 'En curso', completed: 'Completada', error: 'Con error', blocked: 'Bloqueada' }[run.status]}</Text><Text style={{ color: colors.muted, fontSize: 11 }}>{new Date(run.started_at).toLocaleString('es-AR')}</Text><Text selectable style={{ color: colors.text, fontSize: 12, lineHeight: 20 }}>{run.message || 'La tarea todavía no tiene un resultado final.'}</Text><Text style={{ color: colors.muted, fontSize: 10 }}>Registro: {run.id}</Text></View>) : <Text style={{ color: colors.muted, lineHeight: 22 }}>No hay intentos de búsqueda registrados.</Text>}</ScrollView><Button label="Cerrar historial" variant="secondary" onPress={() => setExecutionHistory(null)} /></View></View></Modal>
    <Modal visible={!!extraction} transparent animationType="fade" onRequestClose={() => setExtraction(null)}><View style={styles.overlay}><View style={[styles.extractionCard, { backgroundColor: colors.surface }]}><View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}><View style={{ flex: 1 }}><Text style={{ color: colors.text, fontSize: 22, fontWeight: '600' }}>Texto de tu currículum</Text><Text style={{ color: colors.muted, fontSize: 11, lineHeight: 19, marginTop: 7 }}>{extraction?.message}</Text></View><IconButton icon="close-outline" accessibilityLabel="Cerrar texto extraído" onPress={() => setExtraction(null)} /></View><ScrollView style={{ marginVertical: 19, minHeight: 100 }}><Text selectable style={{ color: colors.text, fontSize: 13, lineHeight: 23 }}>{extraction?.text || 'No se detectó texto en el documento.'}</Text></ScrollView><Text style={{ color: colors.muted, fontSize: 11, lineHeight: 19, marginBottom: 15 }}>Revisá el texto y completá los campos del perfil con los datos que quieras guardar. El perfil no se modificó automáticamente.</Text><Button label="Volver a mi perfil" icon="checkmark-outline" onPress={() => { setExtraction(null); setTab('profile'); }} /></View></View></Modal>
  </SafeAreaView>;
}

export default function App() { return <SafeAreaProvider><ThemeProvider><Workspace /></ThemeProvider></SafeAreaProvider>; }

const styles = StyleSheet.create({
  loading: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 15 }, sidebar: { width: 253, borderRightWidth: 1, paddingHorizontal: 23, paddingTop: 32, paddingBottom: 24 }, brand: { flexDirection: 'row', alignItems: 'center', gap: 10 }, sidebarItem: { flexDirection: 'row', alignItems: 'center', gap: 13, borderRadius: 10, paddingVertical: 15, paddingHorizontal: 13 }, avatar: { width: 36, height: 36, borderRadius: 12, alignItems: 'center', justifyContent: 'center' }, header: { height: 67, borderBottomWidth: 1, flexDirection: 'row', alignItems: 'center', gap: 2 }, demoBanner: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 23, paddingVertical: 9, borderBottomWidth: 1 }, notice: { flexDirection: 'row', alignItems: 'center', gap: 9, paddingLeft: 18, paddingRight: 6, paddingVertical: 6 }, bottomNav: { flexDirection: 'row', borderTopWidth: 1, paddingTop: 10, paddingHorizontal: 8 }, bottomItem: { flex: 1, alignItems: 'center', justifyContent: 'center', minHeight: 48 }, overlay: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(8, 19, 32, .65)', padding: 24 }, extractionCard: { width: '100%', maxWidth: 660, maxHeight: '85%', padding: 25, borderRadius: 20 },
});
