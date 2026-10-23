export function eventPath(eventId: string) {
  return `/radar/${encodeURIComponent(eventId)}`;
}
