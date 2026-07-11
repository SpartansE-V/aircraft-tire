import SimulateLanding from './SimulateLanding'
import Tyres from './Tyres'
import { useRoute } from './ui'

if (location.pathname === '/') history.replaceState(null, '', '/tyres')

export default function App() {
  const path = useRoute()
  return path === '/simulate-landing' ? <SimulateLanding /> : <Tyres />
}
