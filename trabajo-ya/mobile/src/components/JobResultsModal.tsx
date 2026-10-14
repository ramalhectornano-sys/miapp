import React, { useEffect, useRef, useState } from 'react';
import { Linking, Modal, ScrollView, StyleSheet, Text, View } from 'react-native';
import 'react-native-url-polyfill/auto';
import type { FoundJob } from '../types';
import { useTheme } from '../theme/theme';
import { Badge, Button, Card, EmptyState, IconButton } from './ui';

interface Props {
  results: { name: string; jobs: FoundJob[] } | null;
  onClose: () => void;
}

// Offers open only after an explicit tap. Literal IPs and local hostnames are
// unnecessary for a public vacancy and are rejected even if the API supplied them.
function publicOfferUrl(value: string | null): string | null {
  if (!value || value.length > 4096 || !/^https:\/\//i.test(value) || /[\s\u0000-\u001f\u007f\\]/.test(value)) return null;
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:' || url.username || url.password || (url.port && url.port !== '443')) return null;
    const host = url.hostname.toLowerCase().replace(/\.$/, '');
    if (!host || host.length > 253 || host.includes(':') || /^[\d.]+$/.test(host)) return null;
    const labels = host.split('.');
    if (labels.length < 2 || labels.some(label => !/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(label))) return null;
    if (labels.some(label => label === 'localhost') || /\.(?:local|internal|localhost|localdomain|lan|home|intranet|invalid|test|example|onion|arpa|alt)$/.test(host)) return null;
    return url.href;
  } catch { return null; }
}

function observationDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Fecha no informada' : date.toLocaleString('es-AR');
}

function isWebFinding(job: FoundJob): boolean {
  return job.requires_manual_review || /(?:^web(?:[:_-]|$)|tavily)/i.test(job.source);
}

export default function JobResultsModal({ results, onClose }: Props) {
  const { colors } = useTheme();
  const [feedback, setFeedback] = useState<{ id: string; text: string } | null>(null);
  const [openingId, setOpeningId] = useState<string | null>(null);
  const operationVersion = useRef(0);
  const openingLock = useRef(false);

  useEffect(() => {
    operationVersion.current++;
    openingLock.current = false;
    setFeedback(null);
    setOpeningId(null);
    return () => { operationVersion.current++; };
  }, [results]);

  const openOffer = async (job: FoundJob) => {
    if (openingLock.current) return;
    const url = publicOfferUrl(job.url);
    if (!url) {
      setFeedback({ id: job.id, text: 'Esta oferta no tiene un enlace HTTPS público válido para abrir.' });
      return;
    }
    const version = operationVersion.current;
    openingLock.current = true;
    setOpeningId(job.id);
    setFeedback(null);
    try {
      await Linking.openURL(url);
    } catch {
      if (operationVersion.current === version) setFeedback({ id: job.id, text: 'No pudimos abrir la oferta. Revisá tu conexión y volvé a intentarlo.' });
    } finally {
      if (operationVersion.current === version) {
        openingLock.current = false;
        setOpeningId(null);
      }
    }
  };

  return <Modal visible={!!results} transparent animationType="fade" onRequestClose={onClose}>
    <View style={styles.overlay}>
      <View style={[styles.modal, { backgroundColor: colors.surface, borderColor: colors.border }]}>
        <View style={styles.header}>
          <View style={{ flex: 1, gap: 7 }}>
            <Text style={[styles.eyebrow, { color: colors.muted }]}>RESULTADOS PARA REVISAR</Text>
            <Text style={[styles.title, { color: colors.text }]}>Ofertas encontradas</Text>
            <Text style={[styles.description, { color: colors.muted }]}>{results?.name}</Text>
          </View>
          <IconButton icon="close-outline" accessibilityLabel="Cerrar ofertas encontradas" onPress={onClose} />
        </View>
        <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          {!results?.jobs.length ? <EmptyState icon="search-outline" title="Sin ofertas para mostrar" description="No hay resultados disponibles en esta consulta. Podés revisar las fuentes configuradas y el historial de ejecuciones de tu búsqueda." /> : <>
            <Text style={[styles.description, { color: colors.muted }]}>{results.jobs.length === 1 ? '1 resultado disponible para revisar.' : `${results.jobs.length} resultados disponibles para revisar.`}</Text>
            {results.jobs.map(job => {
              const safeUrl = publicOfferUrl(job.url);
              const manual = isWebFinding(job);
              return <Card key={job.id} style={styles.job}>
                <Text style={[styles.company, { color: colors.primary }]}>{job.company || 'Empresa no informada'}</Text>
                <Text style={[styles.jobTitle, { color: colors.text }]}>{job.title || 'Puesto no informado'}</Text>
                <Text style={[styles.description, { color: colors.text }]}>Ciudad: {job.city || 'No informada'}</Text>
                <Text style={[styles.detail, { color: colors.muted }]}>Origen: {job.source === 'verified:greenhouse' ? 'API pública de Greenhouse' : job.source === 'web:tavily' ? 'Búsqueda en Internet' : job.source || 'No informado'}</Text>
                <Text style={[styles.detail, { color: colors.muted }]}>Fecha de consulta: {observationDate(job.observed_at)}</Text>
                <Text style={[styles.description, { color: colors.muted }]}>Coincidencia por puesto y ciudad. Revisá requisitos y vigencia de la oferta antes de postularte.</Text>
                {manual ? <View style={[styles.notice, { backgroundColor: colors.surfaceAlt }]}>
                  <Badge label="Revisión manual" tone="info" icon="eye-outline" />
                  <Text style={[styles.description, { color: colors.muted }]}>Hallazgo para revisión manual. Este enlace no confirma el envío de CV ni verifica correo.</Text>
                </View> : null}
                {!manual && job.recipient_verified && job.recipient_email ? <View style={[styles.notice, { backgroundColor: colors.primarySoft }]}>
                  <Badge label="Canal para CV comprobado al consultar" tone="success" icon="shield-checkmark-outline" />
                  <Text style={[styles.description, { color: colors.text }]}>{job.recipient_email}</Text>
                  {job.evidence?.email ? <Text style={[styles.description, { color: colors.muted }]}>{job.evidence.email}</Text> : null}
                  <Text style={[styles.description, { color: colors.muted }]}>La oferta publicó este correo para recibir CV. Se vuelve a comprobar antes de enviar. Un envío solo se confirma en Mis postulaciones con un comprobante de Gmail.</Text>
                </View> : null}
                {feedback?.id === job.id ? <Text accessibilityRole="alert" style={[styles.description, { color: colors.danger }]}>{feedback.text}</Text> : null}
                {safeUrl ? <Button label="Ver oferta" icon="open-outline" variant="secondary" onPress={() => void openOffer(job)} loading={openingId === job.id} disabled={!!openingId} /> : <Text style={[styles.detail, { color: colors.muted }]}>Enlace público no disponible.</Text>}
              </Card>;
            })}
          </>}
          <Button label="Cerrar" variant="ghost" onPress={onClose} />
        </ScrollView>
      </View>
    </View>
  </Modal>;
}

const styles = StyleSheet.create({
  overlay: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(8, 19, 32, .65)', padding: 18 },
  modal: { width: '100%', maxWidth: 620, maxHeight: '90%', borderRadius: 22, borderWidth: 1, overflow: 'hidden' },
  header: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 22, paddingTop: 22, paddingBottom: 16 },
  content: { paddingHorizontal: 22, paddingBottom: 22, gap: 14 },
  eyebrow: { fontSize: 9, letterSpacing: 1.4, fontWeight: '600' },
  title: { fontSize: 23, fontWeight: '600', letterSpacing: -.5 },
  description: { fontSize: 12, lineHeight: 21 },
  detail: { fontSize: 11, lineHeight: 18 },
  job: { gap: 9, padding: 18 },
  company: { fontSize: 12, lineHeight: 20, fontWeight: '600' },
  jobTitle: { fontSize: 17, lineHeight: 25, fontWeight: '600' },
  notice: { gap: 9, padding: 12, borderRadius: 10, marginVertical: 3 },
});
