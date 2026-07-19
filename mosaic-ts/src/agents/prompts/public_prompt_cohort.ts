export const PUBLIC_BUNDLED_COHORT = "cohort_default" as const;

export function assertPublicBundledCohort(
  cohort: string,
): asserts cohort is typeof PUBLIC_BUNDLED_COHORT {
  if (cohort !== PUBLIC_BUNDLED_COHORT) {
    throw new Error(`private cohort prompt generation is unavailable publicly: ${cohort}`);
  }
}

export function assertPublicBundledCohorts(cohorts: ReadonlyArray<string>): void {
  for (const cohort of cohorts) assertPublicBundledCohort(cohort);
}
