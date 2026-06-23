import os
from crewai import Agent, Task, Crew, Process
from dotenv import load_dotenv

load_dotenv()

# Point to LM Studio running locally (free during development)
os.environ["OPENAI_API_BASE"] = "http://localhost:1234/v1"
os.environ["OPENAI_API_KEY"] = "lm-studio"
os.environ["OPENAI_MODEL_NAME"] = "qwen2.5-coder-7b-instruct"


def run_agent_analysis(ticker: str, market_data: dict, news_chunks: list[str]) -> dict:

    market_summary = f"""
    Ticker: {ticker}
    Current Price: ${market_data.get('current_price', 'N/A')}
    Volume Spike Ratio: {market_data.get('volume_spike_ratio', 'N/A')}x ADV
    Annualized Volatility: {market_data.get('annualized_volatility', 'N/A')}
    ATR-14: {market_data.get('atr_14', 'N/A')}
    """

    news_summary = "\n".join([f"- {chunk}" for chunk in news_chunks[:10]])

    # Agent 1: Chart
    chartist = Agent(
        role="Chartist Analyst",
        goal="Analyse technical market data and determine directional bias",
        backstory="""You are an expert technical analyst who reads price action,
        volume patterns, and volatility metrics to determine whether a stock
        is showing bullish or bearish momentum.""",
        verbose=True,
        allow_delegation=False,
    )

    chartist_task = Task(
        description=f"""Analyse the following market data for {ticker} and determine
        the technical sentiment. Output ONLY a JSON object with these exact keys:
        chartist_sentiment (Bullish/Bearish/Neutral),
        technical_score (0.0 to 1.0 where 1.0 is most bullish),
        technical_reasoning (one sentence explanation).

        Market Data:
        {market_summary}
        """,
        expected_output="A JSON object with chartist_sentiment, technical_score, and technical_reasoning",
        agent=chartist,
    )

    # Agent 2: Macro  
    macro = Agent(
        role="Macro Sentiment Analyst",
        goal="Analyse news and determine market sentiment for a stock",
        backstory="""You are a financial news analyst who reads market news,
        regulatory filings, and earnings transcripts to determine whether
        market sentiment is positive or negative for a given stock.""",
        verbose=True,
        allow_delegation=False,
    )

    macro_task = Task(
        description=f"""Analyse the following recent news headlines and summaries
        for {ticker} and determine the macro sentiment. Output ONLY a JSON object
        with these exact keys:
        macro_sentiment (Bullish/Bearish/Neutral),
        macro_sentiment_score (0.0 to 1.0 where 1.0 is most bullish),
        macro_reasoning (one sentence explanation).

        News:
        {news_summary}
        """,
        expected_output="A JSON object with macro_sentiment, macro_sentiment_score, and macro_reasoning",
        agent=macro,
    )

    # Agent 3: Risk Manager
    risk_manager = Agent(
        role="Risk Manager",
        goal="Reconcile technical and sentiment data to produce a final trade verdict with risk boundaries",
        backstory="""You are a quantitative risk manager who combines technical
        analysis with news sentiment to produce a final directional verdict
        and calculate appropriate stop-loss levels.""",
        verbose=True,
        allow_delegation=False,
    )

    risk_task = Task(
        description=f"""Based on the technical analysis and macro sentiment outputs
        from the previous agents, produce a final risk assessment for {ticker}.
        Output ONLY a JSON object with these exact keys:
        final_bias (Bullish/Bearish/Neutral),
        confidence_score (0.0 to 1.0),
        calculated_stop_loss (price level as a float),
        risk_rationale (one sentence explanation).

        Current price for stop-loss calculation: {market_data.get('current_price', 0)}
        Use ATR of {market_data.get('atr_14', 1.0)} to calculate stop-loss
        (stop-loss = current_price - (2 x ATR) for bullish, current_price + (2 x ATR) for bearish).

        Market Data:
        {market_summary}
        """,
        expected_output="A JSON object with final_bias, confidence_score, calculated_stop_loss, and risk_rationale",
        agent=risk_manager,
        context=[chartist_task, macro_task],
    )

    # Crew
    crew = Crew(
        agents=[chartist, macro, risk_manager],
        tasks=[chartist_task, macro_task, risk_task],
        process=Process.sequential,
        verbose=True,
    )

    result = crew.kickoff()

    print("=== CREW RESULT ===")
    print(type(result))
    print(result)
    print("===================")

    return {
        "ticker": ticker,
        "market_data": market_data,
        "ai_analysis": result.raw if hasattr(result, 'raw') else str(result),
        "backtest_status": "Pending"
    }