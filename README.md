# Sanscry

A comprehensive solution for tracking and analyzing malicious MEV (Maximal Extractable Value) activities on the Solana blockchain, with a focus on sandwich attacks.

## Project Overview

This project aims to create a public, open-source dashboard that reveals and quantifies malicious MEV activities on Solana. The system will:

1. Collect and analyze transaction data using Solana RPC APIs
2. Store processed data in a time-series database
3. Provide a public API for accessing the analysis results
4. Host a self-serve dashboard for visualizing the data

## Key Features

- **Real-time MEV Detection**: Identify sandwich attacks and other malicious MEV activities
- **Data Analysis**:
  - Attack profitability metrics
  - Temporal patterns of attacks
  - Targeted venues and tokens
  - Bot program analysis
  - Validator participation statistics
- **Public API**: Allow other developers to access the analyzed data
- **Interactive Dashboard**: Visualize MEV activities and trends

## Technical Stack

- **Data Collection**: Solana RPC APIs
- **Data Processing**: Python for MEV detection
- **API**: Python
- **Dashboard**: Next.js

## Data Points Tracked

1. **Attack Metrics**
   - Total profit extracted (SOL, stablecoins, memecoins)
   - Per-attack profit estimates
   - Victim losses
   - Priority fees and Jito tips

2. **Temporal Analysis**
   - Attack frequency over time
   - Time-of-day patterns
   - Regional activity (Asian, European, US hours)

3. **Target Analysis**
   - Most targeted tokens
   - Frequently exploited programs
   - High-risk liquidity pools

4. **Bot Analysis**
   - Market share of known sandwich bots
   - Cumulative profits per bot
   - Attack frequency per program

5. **Validator Analysis**
   - Block-level sandwich attack frequency
   - Validator participation statistics

## Implementation Goals

1. Create robust MEV detection algorithms
2. Build scalable data collection and processing pipeline
3. Develop efficient storage solution for time-series data
4. Implement public API with comprehensive endpoints
5. Design and deploy interactive dashboard
6. Ensure system reliability and uptime

## Contributing

This is an open-source project. Contributions are welcome!

## License

MIT License

## Contact

For questions or collaboration opportunities, please reach out to:

- GitHub: [@jbrit](https://github.com/jbrit)
- X: [@jibolaojo](https://x.com/jibolaojo)
- Email: pro.ajibolaojo@gmail.com