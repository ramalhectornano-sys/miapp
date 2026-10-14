import React, { useRef, useState } from 'react';
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View, useWindowDimensions } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import type { ChatMessage, Profile, SearchProposal } from '../types';
import { Badge, BrandMark, Button, Card, Divider } from '../components/ui';
import { useTheme } from '../theme/theme';

interface Props { profile: Profile; messages: ChatMessage[]; busy: boolean; onSend: (text: string) => Promise<void>; onSaveProposal: (messageId: string, proposal: SearchProposal) => Promise<void>; demo: boolean }
const prompts = [
  { icon: 'search-outline' as const, label: 'Buscar un empleo', text: 'Buscá empleos de chofer en Rincón de los Sauces todos los días a las 9 de la mañana. Enviá mi currículum desde mi correo a destinatarios verificados.' },
  { icon: 'document-text-outline' as const, label: 'Mejorar mi perfil', text: 'Ayudame a mejorar mi perfil profesional usando únicamente los datos de mi currículum.' },
  { icon: 'calendar-outline' as const, label: 'Crear una búsqueda', text: 'Quiero configurar una búsqueda semanal de empleo. Ayudame a elegir el puesto, la ciudad y el horario.' },
];
function SearchPreview({ proposal, saved, busy, onSave }: { proposal: SearchProposal; saved?: boolean; busy: boolean; onSave: () => void }) {
  const { colors } = useTheme();
  return <View style={[styles.proposal, { backgroundColor: colors.bg, borderColor: colors.border }]}>
    <View style={styles.row}><View style={[styles.smallIcon, { backgroundColor: colors.primarySoft }]}><Ionicons name="calendar-outline" size={17} color={colors.primary} /></View><View style={{ flex: 1 }}><Text style={{ color: colors.text, fontSize: 13, fontWeight: '600' }}>{proposal.title}</Text><Text style={{ color: colors.muted, fontSize: 11, marginTop: 4 }}>Configuración propuesta</Text></View><Badge label={saved ? 'Guardada' : 'Para confirmar'} tone={saved ? 'success' : 'warning'} /></View>
    <View style={{ gap: 11, marginTop: 18 }}>
      <Detail icon="briefcase-outline" label="Puesto" value={proposal.role} />
      <Detail icon="location-outline" label="Ciudad" value={proposal.city} />
      <Detail icon="time-outline" label="Frecuencia" value={`${proposal.frequency === 'daily' ? 'Todos los días' : 'Cada semana'} · ${proposal.time}`} />
      <Detail icon="globe-outline" label="Zona horaria" value={proposal.timezone} />
    </View>
    <Divider />
    <Text style={{ fontSize: 11, lineHeight: 18, color: colors.muted, marginBottom: 14 }}>{proposal.mode === 'automatic' ? 'El envío automático requiere un consentimiento expreso, un correo conectado y una fuente que verifique destinatarios. Guardar esta propuesta no confirma una búsqueda ni un envío.' : 'Cuando una búsqueda encuentre vacantes, podrás revisar las postulaciones y autorizar cada envío.'}</Text>
    {proposal.mode === 'automatic' && !saved ? <Text style={{ color: colors.muted, fontSize: 11, lineHeight: 18, marginBottom: 15 }}>Después de guardar, confirmás el CV, la cuenta de correo, las fuentes y el vencimiento. La ejecución dependerá de fuentes conectadas y tareas activas del servidor.</Text> : null}
    <Button label={saved ? 'Búsqueda guardada' : 'Confirmar y guardar búsqueda'} icon={saved ? 'checkmark-circle-outline' : 'checkmark-outline'} onPress={onSave} disabled={saved || busy} variant={saved ? 'secondary' : 'primary'} />
  </View>;
}
function Detail({ icon, label, value }: { icon: React.ComponentProps<typeof Ionicons>['name']; label: string; value: string }) {
  const { colors } = useTheme();
  return <View style={{ flexDirection: 'row', alignItems: 'flex-start', gap: 9 }}><Ionicons name={icon} size={14} color={colors.muted} style={{ marginTop: 1 }} /><Text style={{ fontSize: 11, width: 83, color: colors.muted }}>{label}</Text><Text style={{ fontSize: 11, color: colors.text, flex: 1 }}>{value}</Text></View>;
}
export default function AssistantScreen({ profile, messages, busy, onSend, onSaveProposal, demo }: Props) {
  const { colors } = useTheme();
  const { width } = useWindowDimensions();
  const desktop = width >= 1120;
  const [draft, setDraft] = useState('');
  const scrollRef = useRef<ScrollView>(null);
  const inputRef = useRef<TextInput>(null);
  const name = profile.full_name.trim().split(' ')[0] || 'bienvenido';
  const send = async () => { const text = draft.trim(); if (!text || busy) return; setDraft(''); try { await onSend(text); requestAnimationFrame(() => scrollRef.current?.scrollToEnd({ animated: true })); } catch { setDraft(text); } };
  return <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={[styles.screen, { backgroundColor: colors.bg }]}>
    <ScrollView ref={scrollRef} keyboardShouldPersistTaps="handled" contentContainerStyle={[styles.content, { paddingHorizontal: width < 650 ? 20 : 40 }]}>
      <View style={styles.hero}>
        <View style={{ flex: 1 }}><View style={{ flexDirection: 'row', alignItems: 'center', gap: 7, marginBottom: 14 }}><View style={{ width: 5, height: 5, borderRadius: 3, backgroundColor: colors.primary }} /><Text style={[styles.eyebrow, { color: colors.primary }]}>TU PRÓXIMO PASO, MÁS CERCA</Text></View><Text style={[styles.greeting, { color: colors.text, fontSize: width < 650 ? 34 : 43 }]}>Hola, {name}<Text style={{ color: colors.primary }}>.</Text></Text><Text style={[styles.heroText, { color: colors.muted }]}>Encontrar trabajo empieza con una conversación.</Text></View>
        {width >= 750 ? <View style={[styles.heroMark, { borderColor: colors.border, backgroundColor: colors.surface }]}><View style={[styles.markOrbit, { borderColor: colors.border }]}><BrandMark size={49} /></View><Ionicons name="sparkles" size={15} color={colors.primary} style={{ position: 'absolute', top: 15, right: 13 }} /></View> : null}
      </View>
      <View style={[styles.columns, { flexDirection: desktop ? 'row' : 'column' }]}>
        <View style={{ flex: 1, minWidth: 0, gap: 17 }}>
          <Card style={{ padding: 0, overflow: 'hidden' }}>
            <View style={[styles.chatHeading, { borderBottomColor: colors.border }]}><View style={[styles.assistantIcon, { backgroundColor: colors.primarySoft }]}><Ionicons name="sparkles-outline" size={17} color={colors.primary} /></View><View style={{ flex: 1 }}><Text style={{ fontSize: 13, fontWeight: '600', color: colors.text }}>Tu asistente de empleo</Text><Text style={{ fontSize: 10, color: colors.muted, marginTop: 4 }}>{demo ? 'Conversación de demostración' : 'Un plan que se adapta a vos'}</Text></View><Badge label={demo ? 'Demo' : 'IA'} tone={demo ? 'warning' : 'success'} /></View>
            <View style={styles.messages}>
              {messages.length === 0 ? <View style={{ gap: 12 }}><Text style={{ fontSize: 15, lineHeight: 25, color: colors.text }}>Estoy acá para ayudarte a encontrar tu próximo trabajo.</Text><Text style={{ fontSize: 13, lineHeight: 23, color: colors.muted }}>Contame qué puesto buscás, en qué ciudad y cuándo querés que realice la búsqueda. Podemos armar un plan juntos.</Text></View> : messages.map(message => <View key={message.id} style={[styles.message, message.role === 'user' && { alignItems: 'flex-end' }]}>
                <View style={[styles.messageLabel, { flexDirection: message.role === 'user' ? 'row-reverse' : 'row' }]}>{message.role === 'assistant' ? <Ionicons name="sparkles-outline" size={12} color={colors.primary} /> : <Ionicons name="person-outline" size={12} color={colors.muted} />}<Text style={{ fontSize: 10, fontWeight: '600', color: colors.muted }}>{message.role === 'assistant' ? 'TRABAJO YA' : 'VOS'}</Text>{message.demo ? <Text style={{ fontSize: 9, color: colors.warning }}>DEMO</Text> : null}</View>
                <View style={[message.role === 'user' ? styles.userBubble : styles.assistantBubble, { backgroundColor: message.role === 'user' ? colors.primarySoft : 'transparent' }]}><Text selectable style={{ color: colors.text, fontSize: 13, lineHeight: 23 }}>{message.content}</Text></View>
                {message.proposal ? <SearchPreview proposal={message.proposal} saved={message.saved} busy={busy} onSave={() => void onSaveProposal(message.id, message.proposal!)} /> : null}
              </View>)}
              {busy ? <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}><ActivityIndicator color={colors.primary} size="small" /><Text style={{ color: colors.muted, fontSize: 11 }}>Un momento, estoy trabajando en tu solicitud…</Text></View> : null}
            </View>
            <View style={[styles.promptArea, { borderTopColor: colors.border }]}><Text style={{ color: colors.muted, fontSize: 10, marginBottom: 11 }}>PARA EMPEZAR</Text><View style={{ flexDirection: 'row', gap: 8, flexWrap: 'wrap' }}>{prompts.map(prompt => <Pressable key={prompt.label} accessibilityRole="button" onPress={() => { setDraft(prompt.text); inputRef.current?.focus(); }} style={({ pressed }) => [styles.prompt, { borderColor: colors.border, backgroundColor: pressed ? colors.primarySoft : colors.surface }]}><Ionicons name={prompt.icon} size={13} color={colors.primary} /><Text style={{ fontSize: 10, color: colors.text }}>{prompt.label}</Text><Ionicons name="arrow-up-outline" size={11} color={colors.muted} style={{ transform: [{ rotate: '45deg' }] }} /></Pressable>)}</View></View>
          </Card>
          <View style={{ flexDirection: 'row', alignItems: 'flex-start', gap: 8, paddingHorizontal: 3 }}><Ionicons name="shield-checkmark-outline" size={13} color={colors.muted} style={{ marginTop: 2 }} /><Text style={{ fontSize: 10, color: colors.muted, lineHeight: 17, flex: 1 }}>Vos tenés el control. Cada búsqueda se confirma antes de guardarse y cada envío necesita tu autorización. Guardar una configuración no confirma su ejecución; verificá los resultados en el historial.</Text></View>
        </View>
        {desktop ? <View style={{ width: 260, gap: 17 }}>
          <Card style={{ backgroundColor: colors.primarySoft, borderColor: 'transparent' }}><View style={[styles.sidebarIcon, { backgroundColor: colors.surface }]}><Ionicons name="leaf-outline" size={20} color={colors.primary} /></View><Text style={[styles.sidebarTitle, { color: colors.text }]}>Pequeños pasos.{ '\n' }Nuevas oportunidades.</Text><Text style={{ color: colors.muted, fontSize: 11, lineHeight: 20 }}>Tu experiencia tiene valor. Vamos a encontrar dónde puede hacer la diferencia.</Text><View style={[styles.quoteRule, { backgroundColor: colors.primary }]} /><Text style={{ color: colors.primary, fontSize: 9, letterSpacing: 1, fontWeight: '600' }}>A TU RITMO, CON UN PLAN.</Text></Card>
          <Card><Text style={{ color: colors.text, fontSize: 12, fontWeight: '600', marginBottom: 21 }}>Cómo empezamos</Text>{[
            { number: '01', title: 'Contanos sobre vos', subtitle: 'Completá tu perfil y cargá tu CV.', done: !!profile.headline },
            { number: '02', title: 'Definí tu búsqueda', subtitle: 'Un puesto, una ciudad, un horario.', done: false },
            { number: '03', title: 'Revisá y postulate', subtitle: 'Todo queda en tu historial.', done: false },
          ].map((step, index) => <View key={step.number} style={{ flexDirection: 'row', gap: 11, marginBottom: index < 2 ? 24 : 0 }}><View style={[styles.stepNumber, { backgroundColor: colors.surfaceAlt }]}>{step.done ? <Ionicons name="checkmark" size={12} color={colors.primary} /> : <Text style={{ color: colors.muted, fontSize: 9, fontWeight: '600' }}>{step.number}</Text>}</View><View style={{ flex: 1 }}><Text style={{ fontSize: 11, color: colors.text, fontWeight: '600' }}>{step.title}</Text><Text style={{ color: colors.muted, fontSize: 10, lineHeight: 17, marginTop: 5 }}>{step.subtitle}</Text></View></View>)}</Card>
          <View style={{ flexDirection: 'row', gap: 7, paddingHorizontal: 10 }}><Ionicons name="lock-closed-outline" size={12} color={colors.muted} /><Text style={{ color: colors.muted, fontSize: 9, lineHeight: 16, flex: 1 }}>Tu currículum y tus datos son privados.</Text></View>
        </View> : null}
      </View>
    </ScrollView>
    <View style={[styles.composerArea, { backgroundColor: colors.bg, paddingHorizontal: width < 650 ? 20 : 40 }]}><View style={{ width: '100%', maxWidth: 1100, alignSelf: 'center' }}><View style={[styles.composer, { backgroundColor: colors.surface, borderColor: colors.border }]}><TextInput ref={inputRef} value={draft} onChangeText={setDraft} placeholder="Contame qué trabajo estás buscando…" placeholderTextColor={colors.muted} accessibilityLabel="Mensaje para el asistente" multiline maxLength={4000} style={{ flex: 1, maxHeight: 120, paddingVertical: 13, color: colors.text, fontSize: 12, lineHeight: 19 }} onSubmitEditing={Platform.OS === 'web' ? () => void send() : undefined} /><Pressable onPress={() => void send()} disabled={!draft.trim() || busy} accessibilityRole="button" accessibilityLabel="Enviar mensaje" style={({ pressed }) => [styles.send, { backgroundColor: colors.primary, opacity: !draft.trim() || busy ? .4 : pressed ? .7 : 1 }]}><Ionicons name="arrow-up" size={19} color={colors.onPrimary} /></Pressable></View><Text style={{ color: colors.muted, fontSize: 9, textAlign: 'center', marginTop: 9 }}>La IA puede cometer errores. Revisá la información antes de confirmar.</Text></View></View>
  </KeyboardAvoidingView>;
}
const styles = StyleSheet.create({
  screen: { flex: 1 }, content: { flexGrow: 1, paddingTop: 32, paddingBottom: 26, width: '100%', maxWidth: 1180, alignSelf: 'center' },
  hero: { marginBottom: 30, flexDirection: 'row', alignItems: 'center' }, eyebrow: { fontSize: 9, fontWeight: '600', letterSpacing: 1.9 },
  greeting: { fontWeight: '500', letterSpacing: -1.5, lineHeight: 52 }, heroText: { fontSize: 13, lineHeight: 21, marginTop: 8 },
  heroMark: { width: 100, height: 100, borderRadius: 50, borderWidth: 1, alignItems: 'center', justifyContent: 'center', marginRight: 12 }, markOrbit: { width: 74, height: 74, borderWidth: 1, borderRadius: 38, alignItems: 'center', justifyContent: 'center' },
  columns: { gap: 22 }, chatHeading: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 24, paddingVertical: 20, borderBottomWidth: 1, gap: 12 }, assistantIcon: { width: 36, height: 36, borderRadius: 11, alignItems: 'center', justifyContent: 'center' },
  messages: { padding: 25, gap: 24, minHeight: 220 }, message: { gap: 10 }, messageLabel: { gap: 6, alignItems: 'center' },
  userBubble: { borderRadius: 14, borderTopRightRadius: 3, paddingVertical: 12, paddingHorizontal: 16, maxWidth: '92%' }, assistantBubble: { width: '100%' },
  promptArea: { padding: 23, borderTopWidth: 1 }, prompt: { flexDirection: 'row', gap: 7, alignItems: 'center', borderWidth: 1, paddingVertical: 10, paddingHorizontal: 11, borderRadius: 8 },
  proposal: { width: '100%', marginTop: 4, padding: 17, borderWidth: 1, borderRadius: 12 }, row: { flexDirection: 'row', gap: 10, alignItems: 'center' }, smallIcon: { width: 34, height: 34, borderRadius: 9, alignItems: 'center', justifyContent: 'center' },
  sidebarIcon: { width: 41, height: 41, borderRadius: 13, alignItems: 'center', justifyContent: 'center', marginBottom: 18 }, sidebarTitle: { fontSize: 21, lineHeight: 29, fontWeight: '500', letterSpacing: -.6, marginBottom: 12 }, quoteRule: { width: 25, height: 2, marginTop: 23, marginBottom: 12 }, stepNumber: { width: 27, height: 27, borderRadius: 9, alignItems: 'center', justifyContent: 'center' },
  composerArea: { paddingTop: 5, paddingBottom: 14 }, composer: { flexDirection: 'row', alignItems: 'center', gap: 10, borderWidth: 1, borderRadius: 14, paddingHorizontal: 15, minHeight: 58 }, send: { width: 34, height: 34, borderRadius: 10, alignItems: 'center', justifyContent: 'center' },
});

export { AssistantScreen };
