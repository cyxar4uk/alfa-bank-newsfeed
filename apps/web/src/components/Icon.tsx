// Простые линейные иконки 20×20, цвет — от текста.
const paths = {
  home: 'M3 9.5 10 4l7 5.5V16a1 1 0 0 1-1 1h-3.5v-4.5h-5V17H4a1 1 0 0 1-1-1V9.5Z',
  accounts: 'M3 6h14v9H3zM3 9h14M6 12.5h3',
  payments: 'M4 7h10l-3-3M16 13H6l3 3',
  salary: 'M10 3v14M13.5 6.5c0-1.4-1.6-2-3.5-2s-3.5.8-3.5 2.3c0 3.4 7 1.6 7 5 0 1.6-1.6 2.4-3.5 2.4s-3.5-.8-3.5-2.2',
  documents: 'M6 3h6l3 3v11H6zM12 3v3h3M8.5 10h4M8.5 13h4',
  pulse: 'M2.5 10h3.5l2-5 4 10 2-5h3.5',
  bank: 'M3 8 10 4l7 4M4.5 8.5v6M8 8.5v6M12 8.5v6M15.5 8.5v6M3 16.5h14',
  fact: 'M5 4h10v12H5zM8 8h4M8 11h4',
  model: 'M10 3.5 11.6 8.4 16.5 10 11.6 11.6 10 16.5 8.4 11.6 3.5 10 8.4 8.4Z',
  chevronDown: 'm5.5 8 4.5 4.5L14.5 8',
  chevronLeft: 'M12 5 7 10l5 5',
  external: 'M8 5H5v10h10v-3M11 4h5v5M16 4l-7 7',
  check: 'm4.5 10.5 3.5 3.5 7.5-8',
  warning: 'M10 3.5 17.5 16.5h-15L10 3.5ZM10 8.5v3.5M10 14.2v.3',
  user: 'M10 10a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM4 17c.8-3 3.2-4.5 6-4.5s5.2 1.5 6 4.5',
  thumbUp: 'M7 9v8H4V9h3Zm0 0 3.5-5.5c1 0 1.8.8 1.6 1.8L11.6 8H16a1 1 0 0 1 1 1.2l-1.2 6.2a1.5 1.5 0 0 1-1.5 1.1H7',
  thumbDown: 'M7 11V3H4v8h3Zm0 0 3.5 5.5c1 0 1.8-.8 1.6-1.8L11.6 12H16a1 1 0 0 0 1-1.2l-1.2-6.2A1.5 1.5 0 0 0 14.3 3.5H7',
  refresh: 'M15.5 7.5A6 6 0 1 0 16 12M16 4v3.5h-3.5',
  calc: 'M5 3h10v14H5zM7.5 6h5M7.5 10h1M11.5 10h1M7.5 13.5h1M11.5 13.5h1',
} as const;

export type IconName = keyof typeof paths;

export function Icon({ name, size = 20, className }: { name: IconName; size?: number; className?: string }) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[name]} />
    </svg>
  );
}
