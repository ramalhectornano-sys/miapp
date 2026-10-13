import React, { useEffect, useRef, useState } from 'react';
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { BrandMark, Button, Card, Field } from '../components/ui';
import { useTheme } from '../theme/theme';
import { EMAIL_REQUEST_ERROR, EMAIL_VERIFY_ERROR, isValidEmail, isValidEmailCode, normalizeEmail } from '../services/emailAuth';
import { editEmailChallenge, emailCodeRequested, emailCodeWaitSeconds, emailVerificationCredentials, initialEmailChallenge } from '../state/emailChallenge';

interface Props {
  configured: boolean;
  onRequestCode: (email: string, name?: string) => Promise<void>;
  onVerifyCode: (email: string, token: string) => Promise<void>;
  onDemo?: () => void;
}

export default function AuthScreen({ configured, onRequestCode, onVerifyCode, onDemo }: Props) {
  const { colors, dark, toggle } = useTheme();
  const { width } = useWindowDimensions();
  const [challenge, setChallenge] = useState(initialEmailChallenge);
  const [now, setNow] = useState(Date.now);
  const [busy, setBusy] = useState(false);
  const operationPending = useRef(false);
  const [feedback, setFeedback] = useState<{ text: string; error: boolean } | null>(null);
  const codeStep = challenge.requestedEmail !== null;
  const waitSeconds = emailCodeWaitSeconds(challenge, now);

  useEffect(() => {
    if (challenge.resendAt <= Date.now()) return;
    const timer = setInterval(() => {
      const currentTime = Date.now();
      setNow(currentTime);
      if (currentTime >= challenge.resendAt) clearInterval(timer);
    }, 1000);
    return () => clearInterval(timer);
  }, [challenge.resendAt]);

  const requestCode = async () => {
    if (operationPending.current || emailCodeWaitSeconds(challenge, Date.now()) > 0) return;
    setFeedback(null);
    if (!configured) { setFeedback({ text: 'El acceso a tu cuenta todavía no está disponible. Intentá nuevamente cuando se configure el servicio de la aplicación.', error: true }); return; }
    const email = challenge.requestedEmail ?? normalizeEmail(challenge.email);
    if (!isValidEmail(email)) { setFeedback({ text: 'Ingresá un correo electrónico válido.', error: true }); return; }
    operationPending.current = true;
    setBusy(true);
    try {
      await onRequestCode(email, challenge.name.trim() || undefined);
      const requestedAt = Date.now();
      setChallenge(current => emailCodeRequested(current, email, requestedAt));
      setNow(requestedAt);
      setFeedback({ text: 'Revisá tu correo, incluida la carpeta de spam, e ingresá el código recibido.', error: false });
    } catch { setFeedback({ text: EMAIL_REQUEST_ERROR, error: true }); }
    finally { operationPending.current = false; setBusy(false); }
  };

  const verifyCode = async () => {
    if (operationPending.current) return;
    setFeedback(null);
    const credentials = emailVerificationCredentials(challenge);
    if (!credentials || !isValidEmailCode(credentials.token)) {
      setFeedback({ text: 'Ingresá el código de 6 a 8 dígitos que recibiste por correo.', error: true });
      return;
    }
    operationPending.current = true;
    setBusy(true);
    try { await onVerifyCode(credentials.email, credentials.token); }
    catch { setFeedback({ text: EMAIL_VERIFY_ERROR, error: true }); }
    finally { operationPending.current = false; setBusy(false); }
  };

  return <KeyboardAvoidingView style={{ flex: 1, backgroundColor: colors.bg }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
    <ScrollView contentContainerStyle={styles.page} keyboardShouldPersistTaps="handled">
      <View style={styles.top}><View style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}><BrandMark size={34} /><View><Text style={{ color: colors.text, fontSize: 17, fontWeight: '600', letterSpacing: -.5 }}>Trabajo <Text style={{ color: colors.primary }}>YA</Text></Text><Text style={{ color: colors.muted, fontSize: 8, letterSpacing: 1.5, marginTop: 4 }}>TU ASISTENTE DE EMPLEO</Text></View></View><Pressable accessibilityLabel={dark ? 'Activar modo claro' : 'Activar modo oscuro'} accessibilityRole="button" onPress={toggle} style={{ padding: 13 }}><Ionicons name={dark ? 'sunny-outline' : 'moon-outline'} size={20} color={colors.muted} /></Pressable></View>
      <View style={[styles.content, { flexDirection: width >= 950 ? 'row' : 'column', gap: width >= 950 ? 84 : 34 }]}>
        <View style={{ flex: width >= 950 ? 1 : undefined, maxWidth: 500, gap: 18 }}><Text style={{ color: colors.primary, fontSize: 10, fontWeight: '600', letterSpacing: 1.8 }}>TU PRÓXIMO PASO, MÁS CERCA</Text><Text style={{ color: colors.text, fontSize: width >= 950 ? 54 : 39, lineHeight: width >= 950 ? 63 : 47, letterSpacing: -1.8, fontWeight: '500' }}>Tu experiencia.{ '\n' }Nuevas <Text style={{ color: colors.primary }}>oportunidades.</Text></Text><Text style={{ color: colors.muted, fontSize: 14, lineHeight: 24, maxWidth: 390 }}>Un asistente que te ayuda a organizar tu búsqueda laboral, cuidar tu currículum y dar el próximo paso.</Text><View style={{ gap: 17, marginTop: 15 }}>{[
          { icon: 'chatbubble-ellipses-outline' as const, text: 'Contá lo que buscás, con tus propias palabras.' },
          { icon: 'calendar-outline' as const, text: 'Organizá búsquedas con tu puesto y tu ciudad.' },
          { icon: 'shield-checkmark-outline' as const, text: 'Autorizá envíos diarios y consultá cada postulación.' },
        ].map(item => <View key={item.text} style={{ flexDirection: 'row', gap: 11, alignItems: 'center' }}><Ionicons name={item.icon} size={18} color={colors.primary} /><Text style={{ color: colors.muted, fontSize: 12, lineHeight: 21, flex: 1 }}>{item.text}</Text></View>)}</View></View>
        <Card style={{ width: '100%', maxWidth: 440, padding: width < 500 ? 23 : 32, gap: 19 }}><View style={{ gap: 8 }}><Text style={{ color: colors.text, fontSize: 25, letterSpacing: -.7, fontWeight: '600' }}>{codeStep ? 'Revisá tu correo' : 'Entrá sin contraseña'}</Text><Text style={{ color: colors.muted, fontSize: 12, lineHeight: 20 }}>{codeStep ? `Ingresá el código que solicitaste para ${challenge.requestedEmail}.` : 'Usá tu correo para crear tu cuenta o ingresar. Te enviaremos un código de acceso.'}</Text></View>
          {codeStep ? <>
            <Field label="Código de acceso" value={challenge.token} onChangeText={token => setChallenge(current => ({ ...current, token }))} placeholder="Código de 6 a 8 dígitos" keyboardType="number-pad" editable={!busy} />
            <Text style={{ color: colors.muted, fontSize: 11, lineHeight: 18 }}>El código es de un solo uso. Si venció, solicitá uno nuevo.</Text>
          </> : <>
            <Field label="Correo electrónico" value={challenge.email} onChangeText={email => setChallenge(current => ({ ...current, email, token: '' }))} placeholder="vos@ejemplo.com" keyboardType="email-address" editable={!busy} />
            <Field label="Nombre completo (opcional)" value={challenge.name} onChangeText={name => setChallenge(current => ({ ...current, name }))} placeholder="Para tu nueva cuenta" editable={!busy} />
          </>}
          {feedback ? <View style={{ padding: 13, borderRadius: 10, backgroundColor: feedback.error ? `${colors.danger}12` : colors.primarySoft }}><Text accessibilityRole="alert" style={{ color: feedback.error ? colors.danger : colors.primary, fontSize: 12, lineHeight: 20 }}>{feedback.text}</Text></View> : null}
          <Button label={codeStep ? 'Verificar e ingresar' : waitSeconds > 0 ? `Solicitar código en ${waitSeconds}s` : 'Enviar código de acceso'} onPress={() => void (codeStep ? verifyCode() : requestCode())} loading={busy} disabled={!codeStep && waitSeconds > 0} icon="arrow-forward-outline" />
          {codeStep ? <View style={{ gap: 12 }}>
            <Button label={waitSeconds > 0 ? `Reenviar código en ${waitSeconds}s` : 'Reenviar código'} variant="ghost" onPress={() => void requestCode()} disabled={busy || waitSeconds > 0} />
            <Pressable onPress={() => { if (operationPending.current) return; setChallenge(editEmailChallenge); setFeedback(null); }} disabled={busy} accessibilityRole="button"><Text style={{ color: colors.primary, fontSize: 12, textAlign: 'center' }}>Cambiar correo</Text></Pressable>
          </View> : null}
          {onDemo ? <>
            <View style={{ height: 1, backgroundColor: colors.border }} />
            <Button label="Explorar demostración" variant="secondary" icon="sparkles-outline" onPress={onDemo} disabled={busy} />
            <Text style={{ color: colors.muted, fontSize: 10, lineHeight: 18, textAlign: 'center' }}>La demostración usa ejemplos identificados. No se ejecutan búsquedas ni se envían correos.</Text>
          </> : null}
        </Card>
      </View>
      <Text style={{ color: colors.muted, fontSize: 10, lineHeight: 18, textAlign: 'center', marginTop: 45 }}>Tu currículum y tus datos se guardan de forma privada en tu cuenta.</Text>
    </ScrollView>
  </KeyboardAvoidingView>;
}

const styles = StyleSheet.create({ page: { flexGrow: 1, paddingHorizontal: 24, paddingTop: 24, paddingBottom: 35 }, top: { width: '100%', maxWidth: 1080, alignSelf: 'center', flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }, content: { width: '100%', maxWidth: 1080, alignSelf: 'center', flex: 1, justifyContent: 'center', alignItems: 'center', paddingTop: 55, paddingBottom: 20 } });
