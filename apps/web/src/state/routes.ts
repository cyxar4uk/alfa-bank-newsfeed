export function eventPath(eventId: string) {
  return `/radar/${encodeURIComponent(eventId)}`;
}

export function tracePath(traceId: string) {
  return `/radar/trace/${encodeURIComponent(traceId)}`;
}
