import logging

import numpy as np
import pandas as pd
import talib.abstract as ta
import torch
import torch.nn as nn
from pandas import DataFrame
from sklearn.preprocessing import MinMaxScaler

from freqtrade.strategy import CategoricalParameter, DecimalParameter, IntParameter, IStrategy


logger = logging.getLogger(__name__)


class LSTMModel(nn.Module):
    def __init__(self, input_dim, hidden_dim, num_layers, dropout):
        super().__init__()
        self.hidden_dim = hidden_dim
        self.num_layers = num_layers
        self.lstm = nn.LSTM(input_dim, hidden_dim, num_layers, batch_first=True, dropout=dropout)
        self.fc = nn.Sequential(
            nn.Linear(hidden_dim, 32),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(32, 1),
            nn.Sigmoid(),
        )

    def forward(self, x):
        lstm_out, _ = self.lstm(x)
        last_time_step = lstm_out[:, -1, :]
        return self.fc(last_time_step)


class PytorchLSTMStrategy(IStrategy):
    INTERFACE_VERSION = 3

    # Hyperopt parameters - ROI and stoploss
    minimal_roi = {"0": 0.05, "30": 0.03, "60": 0.02}

    stoploss = -0.03
    timeframe = "1h"

    # Model hyperparameters
    sequence_length = IntParameter(30, 100, default=60, space="buy", optimize=True)
    hidden_dim = CategoricalParameter([32, 64, 128], default=64, space="buy", optimize=True)
    num_layers = CategoricalParameter([1, 2, 3], default=2, space="buy", optimize=True)
    dropout = DecimalParameter(0.1, 0.5, default=0.2, space="buy", optimize=True)
    learning_rate = DecimalParameter(0.0001, 0.01, default=0.001, space="buy", optimize=True)
    batch_size = CategoricalParameter([16, 32, 64], default=32, space="buy", optimize=True)

    # Trading parameters
    lstm_threshold_entry = DecimalParameter(0.5, 0.9, default=0.7, space="buy", optimize=True)
    lstm_threshold_exit = DecimalParameter(0.1, 0.5, default=0.3, space="sell", optimize=True)
    rsi_entry = IntParameter(30, 70, default=70, space="buy", optimize=True)
    rsi_exit = IntParameter(70, 90, default=80, space="sell", optimize=True)
    ema_period = IntParameter(50, 200, default=200, space="buy", optimize=True)

    def __init__(self, config):
        super().__init__(config)
        self._model = None
        self._scaler = MinMaxScaler()
        self._scaler_fitted = False
        self._prediction_start = 0
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        logger.info(f"Initializing LSTM Strategy with device: {self.device}")

    def _prepare_data(self, dataframe: DataFrame, fit_scaler: bool = False) -> torch.Tensor:
        features = ["close", "volume", "open", "high", "low"]
        if fit_scaler:
            scaled_data = self._scaler.fit_transform(dataframe[features])
            self._scaler_fitted = True
        elif self._scaler_fitted:
            scaled_data = self._scaler.transform(dataframe[features])
        else:
            return torch.empty((0, self.sequence_length.value, len(features)), device=self.device)
        sequences = np.array(
            [
                scaled_data[i - self.sequence_length.value : i]
                for i in range(self.sequence_length.value, len(scaled_data) - 1)
            ]
        )
        return torch.FloatTensor(sequences).to(self.device)

    def _create_targets(self, dataframe: DataFrame) -> torch.Tensor:
        targets = (dataframe["close"].shift(-1) > dataframe["close"]).astype(int)
        targets = targets[self.sequence_length.value : len(dataframe) - 1].values
        return torch.FloatTensor(targets).to(self.device)

    def _train_model(self, dataframe: DataFrame):
        X = self._prepare_data(dataframe, fit_scaler=True)
        y = self._create_targets(dataframe)

        if len(X) == 0 or len(X) != len(y):
            self._model = None
            return

        self._model = LSTMModel(
            input_dim=5,
            hidden_dim=self.hidden_dim.value,
            num_layers=self.num_layers.value,
            dropout=self.dropout.value,
        ).to(self.device)

        optimizer = torch.optim.Adam(self._model.parameters(), lr=self.learning_rate.value)
        criterion = nn.BCELoss()

        self._model.train()
        for epoch in range(50):
            for i in range(0, len(X), self.batch_size.value):
                batch_X = X[i : i + self.batch_size.value]
                batch_y = y[i : i + self.batch_size.value]
                optimizer.zero_grad()
                outputs = self._model(batch_X)
                loss = criterion(outputs.squeeze(), batch_y)
                loss.backward()
                optimizer.step()

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["ema"] = ta.EMA(dataframe, timeperiod=self.ema_period.value)
        dataframe["macd"], dataframe["macdsignal"], _ = ta.MACD(
            dataframe["close"], fastperiod=12, slowperiod=26, signalperiod=9
        )

        if self._model is None and len(dataframe) >= self.sequence_length.value + 2:
            self._prediction_start = max(
                self.sequence_length.value + 1, int(len(dataframe) * 0.8)
            )
            self._train_model(dataframe.iloc[: self._prediction_start])

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if self._model is not None and len(dataframe) >= self.sequence_length.value:
            self._model.eval()
            with torch.no_grad():
                X = self._prepare_data(dataframe)
                predictions = self._model(X).cpu().numpy()

            pred_series = pd.Series(index=dataframe.index, data=np.nan)
            prediction_end = self.sequence_length.value + len(predictions)
            pred_series.iloc[self.sequence_length.value : prediction_end] = predictions.flatten()
            pred_series.iloc[: self._prediction_start] = np.nan
            dataframe["lstm_prediction"] = pred_series

            dataframe.loc[
                (dataframe["lstm_prediction"] > self.lstm_threshold_entry.value)
                & (dataframe["rsi"] < self.rsi_entry.value)
                & (dataframe["close"] > dataframe["ema"])
                & (dataframe["macd"] > dataframe["macdsignal"]),
                "enter_long",
            ] = 1

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if self._model is not None:
            dataframe.loc[
                (dataframe["lstm_prediction"] < self.lstm_threshold_exit.value)
                | (dataframe["rsi"] > self.rsi_exit.value)
                | (dataframe["macd"] < dataframe["macdsignal"]),
                "exit_long",
            ] = 1

        return dataframe
