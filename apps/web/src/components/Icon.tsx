// Иконки — глифы @alfalab/icons-glyph (MIT), импорт по одной. Иконки со знаком банка не используем.
import type { ComponentType, SVGProps } from 'react';
import { AlertCircleMIcon } from '@alfalab/icons-glyph/AlertCircleMIcon';
import { ArrowRightUpMIcon } from '@alfalab/icons-glyph/ArrowRightUpMIcon';
import { ArrowsRightLeftMIcon } from '@alfalab/icons-glyph/ArrowsRightLeftMIcon';
import { BankMIcon } from '@alfalab/icons-glyph/BankMIcon';
import { BarChartMIcon } from '@alfalab/icons-glyph/BarChartMIcon';
import { BarrelMIcon } from '@alfalab/icons-glyph/BarrelMIcon';
import { BellMIcon } from '@alfalab/icons-glyph/BellMIcon';
import { CalculatorMIcon } from '@alfalab/icons-glyph/CalculatorMIcon';
import { CalendarMIcon } from '@alfalab/icons-glyph/CalendarMIcon';
import { CardMIcon } from '@alfalab/icons-glyph/CardMIcon';
import { ChartLineAscMIcon } from '@alfalab/icons-glyph/ChartLineAscMIcon';
import { CheckmarkMIcon } from '@alfalab/icons-glyph/CheckmarkMIcon';
import { ChevronDownMIcon } from '@alfalab/icons-glyph/ChevronDownMIcon';
import { ChevronLeftMIcon } from '@alfalab/icons-glyph/ChevronLeftMIcon';
import { ChevronRightMIcon } from '@alfalab/icons-glyph/ChevronRightMIcon';
import { ContainerMIcon } from '@alfalab/icons-glyph/ContainerMIcon';
import { DocumentInfoMIcon } from '@alfalab/icons-glyph/DocumentInfoMIcon';
import { DocumentMIcon } from '@alfalab/icons-glyph/DocumentMIcon';
import { DollarRoundedMIcon } from '@alfalab/icons-glyph/DollarRoundedMIcon';
import { DoorArrowRightBoldMIcon } from '@alfalab/icons-glyph/DoorArrowRightBoldMIcon';
import { FactoryMIcon } from '@alfalab/icons-glyph/FactoryMIcon';
import { HandPercentMIcon } from '@alfalab/icons-glyph/HandPercentMIcon';
import { HexagonLinkMIcon } from '@alfalab/icons-glyph/HexagonLinkMIcon';
import { HouseHomeMIcon } from '@alfalab/icons-glyph/HouseHomeMIcon';
import { InformationCircleMIcon } from '@alfalab/icons-glyph/InformationCircleMIcon';
import { MagicWandMIcon } from '@alfalab/icons-glyph/MagicWandMIcon';
import { MagnifierMIcon } from '@alfalab/icons-glyph/MagnifierMIcon';
import { MailMIcon } from '@alfalab/icons-glyph/MailMIcon';
import { MetalGoldMIcon } from '@alfalab/icons-glyph/MetalGoldMIcon';
import { PercentMIcon } from '@alfalab/icons-glyph/PercentMIcon';
import { PinLocationMIcon } from '@alfalab/icons-glyph/PinLocationMIcon';
import { PlusMIcon } from '@alfalab/icons-glyph/PlusMIcon';
import { QuestionCircleMIcon } from '@alfalab/icons-glyph/QuestionCircleMIcon';
import { RadarMIcon } from '@alfalab/icons-glyph/RadarMIcon';
import { RepeatMIcon } from '@alfalab/icons-glyph/RepeatMIcon';
import { SafeBoxMIcon } from '@alfalab/icons-glyph/SafeBoxMIcon';
import { ScalesMIcon } from '@alfalab/icons-glyph/ScalesMIcon';
import { ShoppingCartMIcon } from '@alfalab/icons-glyph/ShoppingCartMIcon';
import { ThumbDownMIcon } from '@alfalab/icons-glyph/ThumbDownMIcon';
import { ThumbUpMIcon } from '@alfalab/icons-glyph/ThumbUpMIcon';
import { UserMIcon } from '@alfalab/icons-glyph/UserMIcon';
import { UsersGroupMIcon } from '@alfalab/icons-glyph/UsersGroupMIcon';
import { UsersMIcon } from '@alfalab/icons-glyph/UsersMIcon';
import { WalletMIcon } from '@alfalab/icons-glyph/WalletMIcon';
import { WorldMIcon } from '@alfalab/icons-glyph/WorldMIcon';

const icons = {
  // разделы банка
  home: HouseHomeMIcon,
  accounts: WalletMIcon,
  payments: ArrowsRightLeftMIcon,
  salary: UsersGroupMIcon,
  documents: DocumentMIcon,
  card: CardMIcon,
  plus: PlusMIcon,
  radar: RadarMIcon,
  search: MagnifierMIcon,
  calendar: CalendarMIcon,
  mail: MailMIcon,
  bell: BellMIcon,
  exit: DoorArrowRightBoldMIcon,
  user: UserMIcon,
  // происхождение утверждений
  fact: DocumentInfoMIcon,
  data: BarChartMIcon,
  bank: BankMIcon,
  model: MagicWandMIcon,
  hypothesis: QuestionCircleMIcon,
  calc: CalculatorMIcon,
  offer: HandPercentMIcon,
  // факторы и каналы
  rate: PercentMIcon,
  deposit: SafeBoxMIcon,
  fx: DollarRoundedMIcon,
  ved: WorldMIcon,
  logistics: ContainerMIcon,
  buyers: UsersMIcon,
  suppliers: FactoryMIcon,
  consumer: ShoppingCartMIcon,
  labor: UsersGroupMIcon,
  gov: ScalesMIcon,
  oil: BarrelMIcon,
  gold: MetalGoldMIcon,
  inflation: ChartLineAscMIcon,
  region: PinLocationMIcon,
  group: HexagonLinkMIcon,
  // служебные
  chevronDown: ChevronDownMIcon,
  chevronLeft: ChevronLeftMIcon,
  chevronRight: ChevronRightMIcon,
  info: InformationCircleMIcon,
  external: ArrowRightUpMIcon,
  check: CheckmarkMIcon,
  warning: AlertCircleMIcon,
  thumbUp: ThumbUpMIcon,
  thumbDown: ThumbDownMIcon,
  refresh: RepeatMIcon,
} satisfies Record<string, ComponentType<SVGProps<SVGSVGElement>>>;

export type IconName = keyof typeof icons;

export function Icon({ name, size = 20, className }: { name: IconName; size?: number; className?: string }) {
  const Glyph = icons[name];
  return <Glyph className={className} width={size} height={size} aria-hidden="true" role="presentation" />;
}
