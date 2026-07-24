// Emergency resource constants. These are baked into the bundle so the
// emergency sheet works offline — never fetched from a server.

export interface EmergencyResource {
  id: string;
  label: string;
  description: string;
  /** Number as displayed to the user. */
  display: string;
  /** tel: href, when the resource is callable. */
  tel?: string;
  /** sms: href, when the resource is textable. */
  sms?: string;
  /** Pre-filled SMS body (e.g. Crisis Text Line keyword). */
  smsBody?: string;
}

export const EMERGENCY_911: EmergencyResource = {
  id: "emergency_911",
  label: "911",
  description: "Emergency — breathing trouble, blue skin, unresponsive, seizure",
  display: "911",
  tel: "tel:911",
};

export const SUICIDE_CRISIS_LIFELINE: EmergencyResource = {
  id: "lifeline_988",
  label: "988 Suicide & Crisis Lifeline",
  description: "Free, confidential, 24/7 — call or text",
  display: "988",
  tel: "tel:988",
  sms: "sms:988",
};

export const CRISIS_TEXT_LINE: EmergencyResource = {
  id: "crisis_text_line",
  label: "Crisis Text Line",
  description: "Text HOME to 741741 — 24/7",
  display: "741741",
  sms: "sms:741741",
  smsBody: "HOME",
};

export const POISON_CONTROL: EmergencyResource = {
  id: "poison_control",
  label: "Poison Control",
  description: "Swallowed something? Free expert help, 24/7",
  display: "1-800-222-1222",
  tel: "tel:18002221222",
};

export const MATERNAL_MENTAL_HEALTH: EmergencyResource = {
  id: "maternal_mental_health",
  label: "Maternal Mental Health Hotline",
  description: "For parents — free, confidential, 24/7",
  display: "1-833-852-6262",
  tel: "tel:18338526262",
};

/** Order matters: most life-critical first. */
export const ALL_EMERGENCY_RESOURCES: EmergencyResource[] = [
  EMERGENCY_911,
  POISON_CONTROL,
  SUICIDE_CRISIS_LIFELINE,
  CRISIS_TEXT_LINE,
  MATERNAL_MENTAL_HEALTH,
];

export function smsHref(resource: EmergencyResource): string | null {
  if (!resource.sms) return null;
  return resource.smsBody
    ? `${resource.sms}?&body=${encodeURIComponent(resource.smsBody)}`
    : resource.sms;
}
