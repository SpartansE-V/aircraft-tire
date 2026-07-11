import SimulateLanding from './SimulateLanding'
import Tyres from './Tyres'
import Rul from './rul/Rul'
import { useRoute } from './ui'

if (location.pathname === '/') history.replaceState(null, '', '/tyres')

export default function App() {
  const path = useRoute()
  if (path === '/simulate-landing') return <SimulateLanding />
  if (path === '/rul') return <Rul />
  return <Tyres />
}
