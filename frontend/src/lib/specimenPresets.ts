export type D638SpecimenType = "I" | "IV" | "V";
export type FemSpecimenShape = "rectangular" | D638SpecimenType;

export interface D638SpecimenPreset {
  type: D638SpecimenType;
  label: string;
  standardRevision: "ASTM D638-22";
  overallLengthMm: number;
  overallWidthMm: number;
  gaugeWidthMm: number;
  narrowLengthMm: number;
  gaugeLengthMm: number;
  gripSeparationMm: number;
  innerRadiusMm: number;
  outerRadiusMm: number | null;
  nominalThicknessMm: number;
  flatTabLengthPerEndMm: number;
  jawEdgeRelativeToFlatStartMm: number;
}

export const D638_PRESETS: Record<D638SpecimenType, D638SpecimenPreset> = {
  I: {
    type: "I",
    label: "ASTM D638 Type I",
    standardRevision: "ASTM D638-22",
    overallLengthMm: 165,
    overallWidthMm: 19,
    gaugeWidthMm: 13,
    narrowLengthMm: 57,
    gaugeLengthMm: 50,
    gripSeparationMm: 115,
    innerRadiusMm: 76,
    outerRadiusMm: null,
    nominalThicknessMm: 3.2,
    flatTabLengthPerEndMm: 32.857625488134026,
    jawEdgeRelativeToFlatStartMm: 7.857625488134026,
  },
  IV: {
    type: "IV",
    label: "ASTM D638 Type IV",
    standardRevision: "ASTM D638-22",
    overallLengthMm: 115,
    overallWidthMm: 19,
    gaugeWidthMm: 6,
    narrowLengthMm: 33,
    gaugeLengthMm: 25,
    gripSeparationMm: 65,
    innerRadiusMm: 14,
    outerRadiusMm: 25,
    nominalThicknessMm: 3.2,
    flatTabLengthPerEndMm: 19.441938862689902,
    jawEdgeRelativeToFlatStartMm: -5.558061137310098,
  },
  V: {
    type: "V",
    label: "ASTM D638 Type V",
    standardRevision: "ASTM D638-22",
    overallLengthMm: 63.5,
    overallWidthMm: 9.53,
    gaugeWidthMm: 3.18,
    narrowLengthMm: 9.53,
    gaugeLengthMm: 7.62,
    gripSeparationMm: 25.4,
    innerRadiusMm: 12.7,
    outerRadiusMm: null,
    nominalThicknessMm: 3.2,
    flatTabLengthPerEndMm: 18.584739587369924,
    jawEdgeRelativeToFlatStartMm: -0.46526041263007656,
  },
};

export function d638Preset(type: D638SpecimenType): D638SpecimenPreset {
  return D638_PRESETS[type];
}
