import { useLocation, useNavigate } from 'react-router-dom';
import { Icon } from './Icon';

/** «Назад» в каждом разделе: на предыдущий экран, а если пришли по прямой ссылке — к новостям. */
export function BackButton({ fallback = '/radar' }: { fallback?: string }) {
  const navigate = useNavigate();
  const location = useLocation();
  return (
    <button
      type="button"
      className="back"
      onClick={() => (location.key !== 'default' ? navigate(-1) : navigate(fallback))}
    >
      <Icon name="chevronLeft" size={18} />
      Назад
    </button>
  );
}
