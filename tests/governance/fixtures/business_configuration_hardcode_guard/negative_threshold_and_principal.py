from decimal import Decimal


class ScenarioRunner:
    def run_stress_scenario(self):
        initial_value = Decimal("1000000")
        return initial_value

    def build_recommendations(self, total_return, max_drawdown):
        messages = []
        if total_return < -0.20:
            messages.append("reduce risk")
        if max_drawdown > 0.30:
            messages.append("add hedge")
        return messages
