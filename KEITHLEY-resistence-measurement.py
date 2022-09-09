""" This program provides a GUI based tool for automated temperature
	dependent resistance measurements using Keithley nanovolt and source
	meters as well as optionally a variety of cryo-cooling hardware.
"""

import os
import time
import Tkinter as tk
import ttk
import tkFileDialog, tkMessageBox
import getpass
from threading import Thread

import csv
import numpy as np

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import (
	FigureCanvasTkAgg, NavigationToolbar2TkAgg)
from matplotlib.figure import Figure

import matplotlib.pyplot as plt
from matplotlib.widgets import Button, TextBox

import pyvisa as visa
from Cryostat import Cryostat

import warnings

class ResistanceMeasurement:

	def __init__(self, SourceMeterPort=24, VoltMeterPort=7, testMode=0):
		""" Initiates the KEITHLEY devices.
		:param SourceMeterPort: GPIB-Portnumber of the Sourcemeter
		:param VoltMeterPort: GPIB-Portnumber of the Nanovoltmeter
		:param testMode: In ~ GUI works without connected hardware
		"""
		self.testMode = testMode
		self.cwd = os.path.join('C:/Users', getpass.getuser(),
								'ResistanceMeasurement')
		if not os.path.exists(self.cwd):
			os.mkdir(self.cwd)

		self.CCcwd = os.path.join('C:\Users', getpass.getuser(), 'AppData',
								  'Roaming', 'CryoConnector', '')

		self.SPort = SourceMeterPort
		self.VPort = VoltMeterPort
		self.I_Range_init = 1e-6
		self.I_Range = self.I_Range_init    # Sourcemeter current range
		self.I_min = 50e-12					# Min sourcemeter current
		self.I_max = 1e-3					# Max safe current
		self.I_compliance = 1e-3			# Compliance current limit
		self.I = self.I_min					# Current setpoint in A
		self.I_opt = self.I_min				# Optimal calibrated setp.
		self.U_min = 5e-6					# Min sourcemeter voltage
		self.U_max = 21.0					# Max safe voltage
		self.U_compliance = 5.9				# Compliance voltage limit
		self.U = self.U_min					# Voltage setpoint in V
		self.T_sample = 300.0				# T @ sample, initially RT
		self.T_cryo = 300.0					# T @ cryostat, initially RT
		self.limit = 5.0					# Limit for R-spread in %
		self.stageList = []					# List of stages in meas.run
		self.XRDlist = ('None',)			# List of XRD sweep names
		self.latestDataPoint = np.array([])	# Latest measurement data

		self.stopFlag = 0					# All measurements stop flag
		self.stopContinuousFlag = 0			# Cont. R-meas. stop flag
		self.exitFlag = 0					# Program has exited flag
		self.plot_request_flag = 0			# Diagram update req. flag
		self.plot_request_function = ''		# Arg. for updatePlot fct.
		self.calibrationFinishedFlag = 0	# Cal. fin. user prompt flag

		self.stopButtonActive = 0			# Stop btn. operational y/n
		self.continuousActive = 0			# Cont. R-meas. active y/n
		self.calibrateActive = 0			# I-calibration active y/n

		path = "TA_to_Tsample_calibration_curve_shield.csv"
		self.calibrationCurve_TA_to_Tsample = path
		path = "Tsample_to_TA_calibration_curve_shield.csv"
		self.calibrationCurve_Tsample_to_TA = path

		self.fig, self.ax = plt.subplots()  # Initiate GUI root window
		self.scatterplot = self.ax.scatter([], [], c='blue')
		self.dataShowing = ''				# For updatePlot function...
		self.dataToSave = 'measurementData'	# For saveFile function ...
		self.delimiter = ','				# Delimiter for save files

		self.rm = visa.ResourceManager()

		self.use_keit = 0					# Use KEITHLEY hardware y/n
		self.use_cryo = 0					# Use cryostat hardware y/n
		self.use_apex = 0					# Use Bruker APEX PC y/n

		self.root = tk.Tk()
		self.root.withdraw()

		self.A = 2.0
		self.B = 1.0
		self.C = 1.0

		self.start()

	# start function to initialise the measurement environment - - - - -

	def _addCryostatButton(self):
		""" Callback function for the Cryostat button in self.start.
		Initialises cryostat.
		"""
		self.cryostat = Cryostat(CCWorkingFolder=self.CCcwd,
								 testMode=self.testMode)
		if self.cryostat.index != -1:
			self.text1.set(self.cryostat.deviceName)
			self.use_cryo = 1

	def connectK2401(self, port):
		""" Attempts to initialise the Keithely K2401 Sourcemeter at the
		provided port.
		"""
		self.K2401 = self.rm.open_resource("GPIB0::{:.0f}::INSTR".format(port))
		self.K2401.read_termination = '\n'
		self.K2401.write_termination = '\n'

		# reset GPIB
		self.K2401.write("*RST")
		# select terminals
		self.K2401.write(":ROUT:TERM REAR")
		# no remote sensing with K2401
		self.K2401.write(":SYST:RSEN OFF")
		# enable auto-zero
		self.K2401.write(":SYST:AZER ON")
		# set to supply current
		self.K2401.write(":SOUR:FUNC CURR")
		# fixed current mode
		self.K2401.write(":SOUR:CURR:MODE FIX")
		# source range
		self.K2401.write(":SOUR:CURR:RANG {:.2e}".format(self.I_Range))
		# source amplitude
		self.K2401.write(":SOUR:CURR:LEV {:.2e}".format(self.I))
		# set compliance limits
		self.K2401.write(":SENS:CURR:PROT:LEV {:.2e}".format(self.I_compliance))
		self.K2401.write(":SENS:VOLT:PROT:LEV {:.2e}".format(self.U_compliance))
		# enable concurrent measurements
		self.K2401.write(":SENS:FUNC:CONC ON")
		# enable all functions
		self.K2401.write(":SENS:FUNC:ON 'VOLT', 'CURR'")
		# specify data elements to return in data string
		self.K2401.write(":FORM:ELEM VOLT, CURR")

	def connectK2182(self, port):
		""" Attempts to initialise the Keithely K2182 Voltmeter at the
		provided port.
		"""
		self.K2182 = self.rm.open_resource("GPIB0::{:.0f}::INSTR".format(port))
		self.K2182.read_termination = '\n'
		self.K2182.write_termination = '\n'

		# reset GPIB
		self.K2182.write("*RST")
		# select voltage
		self.K2182.write(":SENS:FUNC 'VOLT'")
		# select channel 1
		self.K2182.write(":SENS:CHAN 1")
		# auto range on
		self.K2182.write(":SENS:VOLT:CHAN1:RANG:AUTO ON")

	def _testK2401(self):
		""" Tests whether the K2401 is connected to the selected port.
		"""
		try:
			port = int(self.SPortVar.get())
			self.connectK2401(port)
			self.K2401.write("*IDN?")
			IDN = self.K2401.read()
		except:
			IDN = ''
		if ('KEITHLEY' in IDN) and ('2401' in IDN):
			self.use_K2401 = 1
			self.testVar2401.set('ready')
			print 'Connected to: ', IDN
		elif self.testMode:
			self.use_K2401 = 1
			self.testVar2401.set('testMode')
		else:
			self.use_K2401 = 0
			self.testVar2401.set('not found')

	def _testK2182(self):
		""" Tests whether the K2182 is connected to the selected port.
		"""
		try:
			port = int(self.VPortVar.get())
			self.connectK2182(port)
			self.K2182.write("*IDN?")
			IDN = self.K2182.read()
		except:
			IDN = ''
		if ('KEITHLEY' in IDN) and ('2182' in IDN):
			self.use_K2182 = 1
			self.testVar2182.set('ready')
			print 'Connected to: ', IDN
		elif self.testMode:
			self.use_K2182 = 1
			self.testVar2182.set('testMode')
		else:
			self.use_K2182 = 0
			self.testVar2182.set('not found')

	def _keithleyOkButton(self):
		""" Callback function for the OK button.
		"""
		self.use_keit = (self.use_K2401 and self.use_K2182)
		if self.use_keit:
			self.text0.set('K2401 & K2182')
		self.keithleyWindow.destroy()

	def _addKeithleysButton(self):
		""" Callback function for the Keithley Sourcemeter/Voltmeter
		button in self.start. Initialises K2401, K2821.
		"""
		# Keithley device addresses range from 0-30
		ports = range(31)

		self.keithleyWindow = tk.Toplevel(master=self.startWindow)
		self.keithleyWindow.title('Connect to KEITHLEY hardware')

		sms = tk.Label(self.keithleyWindow, text='Please select the appropriate Ports:')
		sms.grid(row=0, column=0, rowspan=2, columnspan=4, padx=30, pady=30)

		sm0 = tk.Label(self.keithleyWindow, text='K2401 Sourcemeter')
		sm0.grid(row=2, column=0, padx=20, sticky='E')

		self.SPortVar = tk.StringVar()
		self.SPortVar.set(self.SPort)
		om0 = tk.OptionMenu(self.keithleyWindow, self.SPortVar, *ports)
		om0.grid(row=2, column=1, sticky='E')

		sb0 = tk.Button(self.keithleyWindow, text='test', command=self._testK2401)
		sb0.grid(row=2, column=2, sticky='W')

		self.testVar2401 = tk.StringVar()
		self._testK2401()
		sm01 = tk.Label(self.keithleyWindow, textvariable=self.testVar2401)
		sm01.grid(row=2, column=3, padx=20, sticky='E')

		sm1 = tk.Label(self.keithleyWindow, text='K2182 Voltmeter')
		sm1.grid(row=3, column=0, padx=20, sticky='E')

		self.VPortVar = tk.StringVar()
		self.VPortVar.set(self.VPort)
		om1 = tk.OptionMenu(self.keithleyWindow, self.VPortVar, *ports)
		om1.grid(row=3, column=1, sticky='E')

		sb1 = tk.Button(self.keithleyWindow, text='test', command=self._testK2182)
		sb1.grid(row=3, column=2, sticky='W')

		self.testVar2182 = tk.StringVar()
		self._testK2182()
		sm11 = tk.Label(self.keithleyWindow, textvariable=self.testVar2182)
		sm11.grid(row=3, column=3, padx=20, sticky='E')

		sb2 = tk.Button(self.keithleyWindow, text='OK', command=self._keithleyOkButton)
		sb2.grid(row=4, column=3, padx=20, pady=20)

		self.keithleyWindow.wait_window()

	def _startOkButton(self):
		""" Callback function for the OK-button in self.start. Decides
		which measurement run to initialise based on the selected
		hardware and closes the startWindow.
		"""
		if (self.use_keit, self.use_cryo, self.use_apex) == (0, 0, 0):
			self.startWindow.destroy()

		elif (self.use_keit, self.use_cryo, self.use_apex) == (1, 0, 0):
			self.startWindow.destroy()
			#self.temperatureRun()
			self.temperatureAutoRunNew()

		elif (self.use_keit, self.use_cryo, self.use_apex) == (1, 1, 0):
			self.startWindow.destroy()
			self.temperatureAutoRunNew()

		else:
			self.startWindow.destroy()

	def start(self):
		""" Asks the user which hardware to connect to and starts the
		measurement GUI.
		"""
		self.startWindow = tk.Toplevel() # when master=root, text breaks
		self.startWindow.title('Configure hardware')

		sm0 = tk.Label(self.startWindow,
					   text='Please choose which hardware to connect to:')
		sm0.grid(row=0, column=0, rowspan=2, columnspan=2, padx=30, pady=30)

		sb0 = tk.Button(self.startWindow,
						text='Source- & Voltmeter',
						command=self._addKeithleysButton)
		sb0.grid(row=2, column=0, padx=20, sticky='EW')

		self.text0 = tk.StringVar()
		self.text0.set('no device selected')
		sl0 = tk.Label(self.startWindow,
					   textvariable=self.text0,
					   font='Helvetica 9 italic')
		sl0.grid(row=2, column=1, sticky='W')

		sb1 = tk.Button(self.startWindow,
						text='Cryostat',
						command=self._addCryostatButton)
		sb1.grid(row=3, column=0, padx=20, sticky='EW')

		self.text1 = tk.StringVar()
		self.text1.set('no device selected')
		sl1 = tk.Label(self.startWindow,
					   textvariable=self.text1,
					   font='Helvetica 9 italic')
		sl1.grid(row=3, column=1, sticky='W')

		sb2 = tk.Button(self.startWindow,
						text='Bruker APEX PC',
						state='disabled')
		sb2.grid(row=4, column=0, padx=20, sticky='EW')

		self.text2 = tk.StringVar()
		self.text2.set('no device selected')
		sl2 = tk.Label(self.startWindow,
					   textvariable=self.text2,
					   font='Helvetica 9 italic')
		sl2.grid(row=4, column=1, sticky='W')

		sb3 = tk.Button(self.startWindow,
						text='OK',
						command=self._startOkButton)
		sb3.grid(column=1, padx=20, pady=20, sticky='E')

		self.startWindow.wait_window()

	# hardware functions to perform calibration and measurements - - - -

	def voltage(self, n=1, deltaMode=1):
		""" Measures voltage directly or via delta-mode. Returns n values
		as array.
		"""
		# Check if OUTPut is already on. Device beeps when OUTPut is
		# turned ON, this is to avoid turning it ON and OFF repeatedly.
		self.K2401.write(":OUTP?")
		outputOnInitially = int(self.K2401.read())

		U = np.zeros(n)
		U_neg = np.ones(n)
		self.K2401.write(":SOUR:CURR:RANG {:.2e}".format(self.I))
		self.K2401.write(":SOUR:CURR:LEV {:.2e}".format(self.I))

		if not outputOnInitially:
			self.K2401.write(":OUTP ON")

		for i in range(n):
			self.K2182.write(":READ?")
			U[i] = float(self.K2182.read())
			if deltaMode == 1:
				# switch current and calculate average
				self.K2401.write(":SOUR:CURR:LEV {:.2e}".format(-self.I))
				self.K2182.write(":READ?")
				U_neg[i] = float(self.K2182.read())
				self.K2401.write(":SOUR:CURR:LEV {:.2e}".format(self.I))

		if not outputOnInitially:
			self.K2401.write(":OUTP OFF")

		if deltaMode == 1:
			U = 0.5*(U - U_neg)
		if n == 1:
			U = U[0]
		return U

	def sense_UIR(self):
		"""
		Measures voltage, current and resistance at the power supply.
		:return: U, I, R
		"""
		U = I = R = 0.0
		self.K2401.write(":OUTP?")
		outputOnInitially = int(self.K2401.read())

		if outputOnInitially:
			self.K2401.write(":READ?")
			datastring = self.K2401.read()
			stringarray = datastring.split(',')
			U = float(stringarray[0])
			I = float(stringarray[1])
			self.latest_I = I
			R = U/I
		return U, I, R

	def resistance(self, n=1, deltaMode=1):
		"""
		Four-point resistance measurement using voltage() and sense_UIR().
		Returns n values as array, or float if n==1.
		"""
		# Check if OUTPut is already on. Device beeps when OUTPut is
		# turned ON, this is to avoid turning it ON and OFF repeatedly.
		self.K2401.write(":OUTP?")
		outputOnInitially = int(self.K2401.read())

		U = np.zeros(n)
		I = np.zeros(n)
		U_neg = np.ones(n)
		I_neg = np.zeros(n)
		self.K2401.write(":SOUR:CURR:LEV {:.2e}".format(self.I))

		if not outputOnInitially:
			self.K2401.write(":OUTP ON")

		for i in range(n):
			self.K2182.write(":READ?")
			U[i] = float(self.K2182.read())
			_, I[i], _ = self.sense_UIR()
			if deltaMode == 1:
				# switch current and calculate average
				self.K2401.write(":SOUR:CURR:LEV {:.2e}".format(-self.I))
				self.K2182.write(":READ?")
				U_neg[i] = float(self.K2182.read())
				_, I_neg[i], _ = self.sense_UIR()
				self.K2401.write(":SOUR:CURR:LEV {:.2e}".format(self.I))

		if not outputOnInitially:
			self.K2401.write(":OUTP OFF")

		R = U/I
		if deltaMode == 1:
			R_neg = U_neg/I_neg
			R = 0.5*(R - R_neg)
		if n == 1:
			R = R[0]
		return R

	def calibrate(self, n=10, step=10, wait=0.0, plot=0):
		""" Ramps up the current until spread of measured resistances
		(std) is smaller than the self.limit in %.

		:param n: The number of measurements per current setting
		:param step: The multiplicative increase of the current
		setpoint until desired precision is reached
		:param wait: Time in s to wait between measurements of R
		:param plot: Boolean to determine whether to self.updatePlot
		"""
		self.dataToSave = 'calibrationData'

		rel_max = self.limit*0.01
		self.I = self.I_min
		slow = 0
		t0 = time.time()
		Rarrayplus = np.zeros(n)
		Rarrayminus = np.zeros(n)

		self.CaliHead = np.array([["T_sample", "T_cryo", "I", "U", "R", "t"],
								  ["K", "K", "A", "V", "Ohms", "s"]])

		self.K2401.write(":OUTP ON")

		#path = os.path.join(self.cwd, 'cali.out')
		path = self.filePath
		with open(path, 'w') as file:
			for line in self.CaliHead:
				string = self.delimiter.join(str(x) for x in line)
				file.write(string + '\n')
		while self.stopFlag == 0:
			if (abs(self.I) > self.I_max) and (slow == 0):
				slow = 1
				if step > 5.0:
					self.I = self.I/step
					step = step/5.0
					self.I = step * self.I
				else:
					self.I = self.I_max
			if (abs(self.I) > self.I_max) and (slow == 1):
				self.I = self.I_min
				self.I_Range = self.I_Range_init
				print "Calibration failed: Reached current threshold before " \
					  "measurement spread within limits!"
				print "Current setpoint returned to {} A.\n".format(self.I)
				break
			print "Calibrating... I = {} A".format(self.I)
			self.t2.set_val(self.I)

			# n times resistance with self.I in one direction (plus)
			for i in range(n):
				if self.stopFlag:
					break

				if not ((abs(self.I) == self.I_min) and (i == 0)):
					time.sleep(wait)

				if self.use_cryo:
					self.cryostat.updateStatus()
					self.T_cryo = self.cryostat.cryoTemp
					self.T_sample = self.cryostat.sampleTemp

				t = time.time() - t0
				U = self.voltage(n=1, deltaMode=0)
				_, I, _ = self.sense_UIR()
				R = U/I
				Rarrayplus[i] = R

				data = np.array([self.T_sample, self.T_cryo, I, U, R, t])
				self.latestDataPoint = data

				data_string = self.delimiter.join(str(x) for x in data)
				with open(path, 'a') as file:
					file.write(data_string + '\n')

				if plot:
					self._temperatureRun_updatePlot(function='calibrate')
					# Avoid Matplotlib window crashing:
					#plt.pause(0.05)
					# actually makes Matplotlib window crash when running function in Thread

			# n times resistance with self.I in other direction (minus)
			self.I = -self.I
			for i in range(n):
				if self.stopFlag:
					break

				if not ((abs(self.I) == self.I_min) and (i == 0)):
					time.sleep(wait)

				if self.use_cryo:
					self.cryostat.updateStatus()
					self.T_cryo = self.cryostat.cryoTemp
					self.T_sample = self.cryostat.sampleTemp

				t = time.time() - t0
				U = self.voltage(n=1, deltaMode=0)
				_, I, _ = self.sense_UIR()
				R = U / I
				Rarrayminus[i] = R

				data = np.array([self.T_sample, self.T_cryo, I, U, R, t])
				self.latestDataPoint = data

				data_string = self.delimiter.join(str(x) for x in data)
				with open(path, 'a') as file:
					file.write(data_string + '\n')

				if plot:
					self._temperatureRun_updatePlot(function='calibrate')
					# Avoid Matplotlib window crashing:
					#plt.pause(0.05)
					# actually makes Matplotlib window crash when running function in Thread
			self.I = -self.I

			avgplus = Rarrayplus.sum()/n
			avgminus = Rarrayminus.sum()/n
			stdplus = Rarrayplus.std()
			stdminus = Rarrayminus.std()
			avg = (avgplus + avgminus)/2
			std = (stdplus + stdminus)/2
			rel = abs(std/avg)
			print "Spread = {} %\n".format(rel*100)
			if rel < rel_max:
				print "Calibration successful: Current setpoint set to " \
					  "{} A.\n".format(self.I)
				break
			self.I = step * self.I
			self.I_Range = self.I

		self.K2401.write(":OUTP OFF")
		self.calibrateActive = 0
		self.b0.color = 'lightgray'
		self.b0.hovercolor = 'lightskyblue'
		self.b0.label.set_text('Calibrate I')

	def IVcurve(self, n=10, step=10, wait=0.0, plot=0):
		""" Ramps up the voltage and maps current.

		:param n: The number of measurements per voltage setting
		:param step: The multiplicative increase of the voltage
		setpoint
		:param wait: Time in s to wait between measurements of I
		:param plot: Boolean to determine whether to self.updatePlot
		"""
		self.dataToSave = 'IVcurveData'
		reachedEnd = 0
		self.U = self.U_min

		t0 = time.time()

		self.IVcurveHead = np.array([["T_sample", "T_cryo", "U_source", "I_sense", "R_calc", "U_sample", "t"],
								  ["K", "K", "V", "A", "Ohms", "V", "s"]])

		# set to supply voltage
		self.K2401.write(":SOUR:FUNC VOLT")
		self.K2401.write(":SOUR:VOLT:LEV {:.2e}".format(self.U))
		self.K2401.write(":OUTP ON")

		#path = os.path.join(self.cwd, 'IVcurve.out')
		path = self.filePath
		with open(path, 'w') as file:
			for line in self.IVcurveHead:
				string = self.delimiter.join(str(x) for x in line)
				file.write(string + '\n')
		while self.stopFlag == 0:
			if (abs(self.U) >= self.U_max):
				if reachedEnd:
					self.U = self.U_min
					break
				else:
					self.U = self.U_max
					reachedEnd = 1
			print "Calibrating... I = {} V".format(self.U)

			# n times current with self.U in one direction (plus)
			self.K2401.write(":SOUR:VOLT:LEV {:.2e}".format(self.U))
			for i in range(n):
				if self.stopFlag:
					break

				self.K2401.write(":SOUR:VOLT:LEV {:.2e}".format(self.U))

				if not ((abs(self.U) == self.U_min) and (i == 0)):
					time.sleep(wait)

				if self.use_cryo:
					self.cryostat.updateStatus()
					self.T_cryo = self.cryostat.cryoTemp
					self.T_sample = self.cryostat.sampleTemp

				t = time.time() - t0
				# Sourcemeter voltage, current and resistance
				U, I, R = self.sense_UIR()
				# Voltmeter voltage at sample
				self.K2182.write(":READ?")
				U_sample = float(self.K2182.read())

				data = np.array([self.T_sample, self.T_cryo, U, I, R, U_sample, t])
				self.latestDataPoint = data

				data_string = self.delimiter.join(str(x) for x in data)
				with open(path, 'a') as file:
					file.write(data_string + '\n')

				if plot:
					self._temperatureRun_updatePlot(function='IVcurve')
					# Avoid Matplotlib window crashing:
					#plt.pause(0.05)
					# actually makes Matplotlib window crash when running function in Thread

			# n times resistance with self.I in other direction (minus)
			self.U = -self.U
			self.K2401.write(":SOUR:VOLT:LEV {:.2e}".format(self.U))
			for i in range(n):
				if self.stopFlag:
					break

				if not ((abs(self.U) == self.U_min) and (i == 0)):
					time.sleep(wait)

				if self.use_cryo:
					self.cryostat.updateStatus()
					self.T_cryo = self.cryostat.cryoTemp
					self.T_sample = self.cryostat.sampleTemp

				t = time.time() - t0
				# Sourcemeter voltage, current and resistance
				U, I, R = self.sense_UIR()
				# Voltmeter voltage at sample
				self.K2182.write(":READ?")
				U_sample = float(self.K2182.read())

				data = np.array([self.T_sample, self.T_cryo, U, I, R, U_sample, t])
				self.latestDataPoint = data

				data_string = self.delimiter.join(str(x) for x in data)
				with open(path, 'a') as file:
					file.write(data_string + '\n')

				if plot:
					self._temperatureRun_updatePlot(function='IVcurve')
					# Avoid Matplotlib window crashing:
					#plt.pause(0.05)
					# actually makes Matplotlib window crash when running function in Thread
			self.U = -self.U

#			avgplus = Rarrayplus.sum()/n
#			avgminus = Rarrayminus.sum()/n
#			stdplus = Rarrayplus.std()
#			stdminus = Rarrayminus.std()
#			avg = (avgplus + avgminus)/2
#			std = (stdplus + stdminus)/2
#			rel = abs(std/avg)
#			print "Spread = {} %\n".format(rel*100)
#			if rel < rel_max:
#				print "Calibration successful: Current setpoint set to " \
#					  "{} A.\n".format(self.I)
#				break
			self.U = step * self.U

		# turn off output
		self.K2401.write(":OUTP OFF")
		# set to supply current
		self.K2401.write(":SOUR:FUNC CURR")
		self.calibrateActive = 0
		self.b0.color = 'lightgray'
		self.b0.hovercolor = 'lightskyblue'
		self.b0.label.set_text('Calibrate I')

	def URUIR(self, n=1, deltaMode=1):
		"""
		Returns all measurement functions as arrays of length n.
		:param n:
		:param deltaMode:
		:return: U_sample, R_sample, U_source, I_source, R_source
		"""
		# Check if OUTPut is already on. Device beeps when OUTPut is
		# turned ON, this is to avoid turning it ON and OFF repeatedly.
		self.K2401.write(":OUTP?")
		outputOnInitially = int(self.K2401.read())

		U_sample = np.zeros(n)
		U_sample_neg = np.zeros(n)
		R_sample = np.zeros(n)
		R_sample_neg = np.zeros(n)
		U_source = np.zeros(n)
		U_source_neg = np.zeros(n)
		I_source = np.zeros(n)
		I_source_neg = np.zeros(n)
		R_source = np.zeros(n)
		R_source_neg = np.zeros(n)

		if not outputOnInitially:
			self.K2401.write(":SOUR:CURR:LEV {:.2e}".format(self.I))
			self.K2401.write(":OUTP ON")

		for i in range(n):
			self.K2182.write(":READ?")
			U_sample[i] = float(self.K2182.read())
			U_source[i], I_source[i], R_source[i] = self.sense_UIR()
			if deltaMode == 1:
				# switch current and calculate average
				self.K2401.write(":SOUR:CURR:LEV {:.2e}".format(-self.I))
				self.K2182.write(":READ?")
				U_sample_neg[i] = float(self.K2182.read())
				U_source_neg[i], I_source_neg[i], R_source_neg[i] = self.sense_UIR()
				self.K2401.write(":SOUR:CURR:LEV {:.2e}".format(self.I))

		if not outputOnInitially:
			self.K2401.write(":OUTP OFF")

		R_sample = U_sample/I_source
		if deltaMode == 1:
			R_sample_neg = U_sample_neg/I_source_neg
			R_sample = 0.5*(R_sample + R_sample_neg)
			R_source = 0.5*(R_source + R_source_neg)
		if n == 1:
			U_sample = U_sample[0]
			R_sample = R_sample[0]
			U_source = U_source[0]
			I_source = I_source[0]
			R_source = R_source[0]
		return U_sample, R_sample, U_source, I_source, R_source

	def calibrateNew(self, n=10, step=10, wait=0.0, plot=0):
		""" Ramps up the voltage and maps current.

		:param n: The number of measurements per voltage setting
		:param step: The multiplicative increase of the voltage
		setpoint
		:param wait: Time in s to wait between measurements of I
		:param plot: Boolean to determine whether to self.updatePlot
		"""
		while self.calibrationFinishedFlag:
			time.sleep(0.01)
		reachedEnd = 0
		self.U = self.U_min

		t0 = time.time()

		self.IVcurveHead = np.array([["T_sample", "T_cryo", "U_setpoint", "U_sample", "R_sample", "DR", "U_source", "I_source", "R_source", "t"],
							 ["K", "K", "V", "V", "Ohms", "Ohms", "V", "A", "Ohms", "s"]])

		# set to supply voltage
		self.K2401.write(":SOUR:FUNC VOLT")
		self.K2401.write(":SOUR:VOLT:LEV {:.2e}".format(self.U))
		self.K2401.write(":OUTP ON")

		path = self.filePath
		with open(path, 'w') as file:
			for line in self.IVcurveHead:
				string = self.delimiter.join(str(x) for x in line)
				file.write(string + '\n')

		# The below while loop will fill in these arrays using the
		# append method, and the counter 'k' to read the latest entry.
		U_stp = np.array([])
		U_avg = np.array([])
		R_avg = np.array([])
		DR = np.array([])
		I_avg = np.array([])

		k = 0
		while self.stopFlag == 0:
			if (abs(self.U) >= self.U_max):
				if reachedEnd:
					self.U = self.U_min
					break
				else:
					self.U = self.U_max
					reachedEnd = 1
			print "Calibrating... I = {} V".format(self.U)

			# n times current with self.U in one direction (plus)
			T_sample = np.zeros(n)
			T_cryo = np.zeros(n)
			U_sample = np.zeros(n)
			R_sample = np.zeros(n)
			U_source = np.zeros(n)
			I_source = np.zeros(n)
			R_source = np.zeros(n)
			t = np.zeros(n)

			self.K2401.write(":SOUR:VOLT:LEV {:.2e}".format(self.U))
			for i in range(n):
				if self.stopFlag:
					break

				self.K2401.write(":SOUR:VOLT:LEV {:.2e}".format(self.U))

				if not ((abs(self.U) == self.U_min) and (i == 0)):
					time.sleep(wait)

				if self.use_cryo:
					self.cryostat.updateStatus()
					self.T_cryo = T_cryo[i] = self.cryostat.cryoTemp
					self.T_sample = T_sample[i] = self.cryostat.sampleTemp
				else:
					T_sample[i] = self.T_sample
					T_cryo[i] = self.T_cryo

				t[i] = time.time() - t0
				# Sourcemeter voltage, current and resistance
				U_source[i], I_source[i], R_source[i] = self.sense_UIR()
				# Voltmeter voltage at sample
				self.K2182.write(":READ?")
				U_sample[i] = float(self.K2182.read())
				R_sample[i] = U_sample[i] / I_source[i]

				self.latestDataPoint = np.array([U_source[i], I_source[i]])
				if plot:
					#self._temperatureAutoRunNew_updatePlot(function='IVcurve')
					while self.plot_request_flag:
						# wait for previous plot call to finish
						time.sleep(0.01)
					self.plot_request_function = 'IVcurve'
					self.plot_request_flag = 1

			if self.stopFlag:
				break

			# Compute secondary values (avg etc.) and write to file
			U_stp = np.append(U_stp, self.U)
			U_avg = np.append(U_avg, np.average(U_source))
			R_avg = np.append(R_avg, np.average(R_sample))
			DR = np.append(DR, np.std(R_sample))
			I_avg = np.append(I_avg, np.average(I_source))
			with open(path, 'a') as file:
				for i in range(n):
					data = np.array([T_sample[i],
									 T_cryo[i],
									 self.U,
									 U_sample[i],
									 R_sample[i],
									 DR[k],
									 U_source[i],
									 I_source[i],
									 R_source[i],
									 t[i]])
					data_string = self.delimiter.join(str(x) for x in data)
					file.write(data_string + '\n')

			self.latestDataPoint = np.array([I_avg[k], R_avg[k], DR[k]])
			if plot:
				#self._temperatureAutoRunNew_updatePlot(function='calibrate')
				while self.plot_request_flag:
					# wait for previous plot call to finish
					time.sleep(0.01)
				self.plot_request_function = 'calibrate'
				self.plot_request_flag = 1

			k += 1
			self.U = -self.U

			# n times resistance with self.I in other direction (minus)
			T_sample = np.zeros(n)
			T_cryo = np.zeros(n)
			U_sample = np.zeros(n)
			R_sample = np.zeros(n)
			U_source = np.zeros(n)
			I_source = np.zeros(n)
			R_source = np.zeros(n)
			t = np.zeros(n)

			self.K2401.write(":SOUR:VOLT:LEV {:.2e}".format(self.U))
			for i in range(n):
				if self.stopFlag:
					break

				if not ((abs(self.U) == self.U_min) and (i == 0)):
					time.sleep(wait)

				if self.use_cryo:
					self.cryostat.updateStatus()
					self.T_cryo = T_cryo[i] = self.cryostat.cryoTemp
					self.T_sample = T_sample[i] = self.cryostat.sampleTemp
				else:
					T_cryo[i] = self.T_cryo
					T_sample[i] = self.T_sample

				t[i] = time.time() - t0
				# Sourcemeter voltage, current and resistance
				U_source[i], I_source[i], R_source[i] = self.sense_UIR()
				# Voltmeter voltage at sample
				self.K2182.write(":READ?")
				U_sample[i] = float(self.K2182.read())
				R_sample[i] = U_sample[i] / I_source[i]

				self.latestDataPoint = np.array([U_source[i], I_source[i]])
				if plot:
					#self._temperatureAutoRunNew_updatePlot(function='IVcurve')
					while self.plot_request_flag:
						# wait for previous plot call to finish
						time.sleep(0.01)
					self.plot_request_function = 'IVcurve'
					self.plot_request_flag = 1

			if self.stopFlag:
				break

			# Compute secondary values (avg etc.) and write to file
			U_stp = np.append(U_stp, self.U)
			U_avg = np.append(U_avg, np.average(U_source))
			R_avg = np.append(R_avg, np.average(R_sample))
			DR = np.append(DR, R_sample.std())
			I_avg = np.append(I_avg, np.average(I_source))
			with open(path, 'a') as file:
				for i in range(n):
					data = np.array([T_sample[i],
									 T_cryo[i],
									 self.U,
									 U_sample[i],
									 R_sample[i],
									 DR[k],
									 U_source[i],
									 I_source[i],
									 R_source[i],
									 t[i]])
					data_string = self.delimiter.join(str(x) for x in data)
					file.write(data_string + '\n')

			self.latestDataPoint = np.array([I_avg[k], R_avg[k], DR[k]])
			if plot:
				#self._temperatureAutoRunNew_updatePlot(function='calibrate')
				while self.plot_request_flag:
					# wait for previous plot call to finish
					time.sleep(0.01)
				self.plot_request_function = 'calibrate'
				self.plot_request_flag = 1

			k += 1
			self.U = -self.U

#			avgplus = Rarrayplus.sum()/n
#			avgminus = Rarrayminus.sum()/n
#			stdplus = Rarrayplus.std()
#			stdminus = Rarrayminus.std()
#			avg = (avgplus + avgminus)/2
#			std = (stdplus + stdminus)/2
#			rel = abs(std/avg)
#			print "Spread = {} %\n".format(rel*100)
#			if rel < rel_max:
#				print "Calibration successful: Current setpoint set to " \
#					  "{} A.\n".format(self.I)
#				break
			self.U = step * self.U

		# turn off output
		self.K2401.write(":OUTP OFF")
		# set to supply current
		self.K2401.write(":SOUR:FUNC CURR")
		self.calibrateActive = 0

		if len(I_avg) >= 6:
			# Positive voltages branch:
			U_stp_pos = U_stp[U_stp>0]
			U_avg_pos = U_avg[U_stp>0]
			R_avg_pos = R_avg[U_stp>0]
			DR_pos = DR[U_stp>0]
			I_avg_pos = I_avg[U_stp>0]
			n_pos = len(U_stp_pos)

			# Gradient of the positive IV branch
			I_1abl_pos = np.gradient(I_avg_pos, U_avg_pos)
			I_2abl_pos = np.gradient(I_1abl_pos, U_avg_pos)

			# Negative voltages branch:
			U_stp_neg = U_stp[U_stp<0]
			U_avg_neg = U_avg[U_stp<0]
			R_avg_neg = R_avg[U_stp<0]
			DR_neg = DR[U_stp<0]
			I_avg_neg = I_avg[U_stp<0]
			n_neg = len(U_stp_neg)

			# Gradient for the negative IV branch
			I_1abl_neg = np.gradient(I_avg_neg, U_avg_neg)
			I_2abl_neg = np.gradient(I_1abl_neg, U_avg_neg)

			# Calculate merit function which takes into account linearity
			# (ohmic behavior), statistical uncertainty (precision) and
			# voltage square (ohmic heating power)
			f1_pos = np.abs(I_2abl_pos) / np.max(np.abs(I_2abl_pos))
			f2_pos = DR_pos / np.max(DR_pos)
			f3_pos = np.abs(U_avg_pos**2) / np.max(np.abs(U_avg_pos**2))
			merit_function_pos = self.A * f1_pos + self.B * f2_pos + self.C * f3_pos

			f1_neg = np.abs(I_2abl_neg) / np.max(np.abs(I_2abl_neg))
			f2_neg = DR_neg / np.max(DR_neg)
			f3_neg = np.abs(U_avg_neg**2) / np.max(np.abs(U_avg_neg**2))
			merit_function_neg = self.A * f1_neg + self.B * f2_neg + self.C * f3_neg

			merit_function_tot = merit_function_neg + merit_function_pos[:n_neg]

			index_opt_pos = np.argmin(merit_function_pos)
			index_opt_neg = np.argmin(merit_function_neg)
			index_opt_tot = np.argmin(merit_function_tot)
			print merit_function_tot
			print index_opt_tot

			self.U_opt = U_stp_pos[index_opt_tot]
			self.I_opt = I_avg_pos[index_opt_tot]
			self.calibrationFinishedFlag = 1


	# GUI components for the different measurement runs  - - - - - - - -

	def stop(self):
		""" Raises stop flag, disables stop button.
		"""
		self.stopFlag = 1
		message = 'Stopped'
		try:
			self._temperatureAutoRun_updateStatus(message=message, showcolor=0)
		except AttributeError:
			pass
		self.stopButtonActive = self._temperatureAutoRun_updateStopButton('OFF')

	def _temperatureRun_updatePlot(self, function='measure'):
		""" Updates plot with latest data. Changes axes depending on
		function, either R over T (function = measure) or R over t
		(function = calibrate, continuous.)
		"""
		if function == 'measure':
			if self.dataShowing == 'measurementData':
				xdata = self.latestDataPoint[0]
				ydata = self.latestDataPoint[4]
				# Add single data point:
				self.ax.plot(xdata, ydata, c='tab:blue', marker='o')
				self.fig.canvas.draw()
			else:
				self.ax.clear()
				self.ax.set_title('Current measurement run:')
				self.ax.set_ylabel('Resistance [Ohms]')
				self.ax.set_xlabel('Temperature [K]')

				#path = os.path.join(self.cwd, 'temp.out')
				path = self.filePath
				with open(path, 'r') as file:
					for line in file.read().splitlines()[2:]:
						data = [float(x) for x in line.split(',')]
						xdata = data[0]
						ydata = data[4]
						# Add single data point:
						self.ax.plot(xdata, ydata, c='tab:blue', marker='o')
				self.fig.canvas.draw()

				self.dataShowing = 'measurementData'
				self.dataToSave = 'measurementData'

		elif function == 'calibrate':
			if self.dataShowing == 'callibrationData':
				xdata = self.latestDataPoint[5]
				ydata = self.latestDataPoint[4]
				# Add single data point:
				self.ax.plot(xdata, ydata, c='tab:red', marker='o')
				self.fig.canvas.draw()
			else:
				self.ax.clear()
				self.ax.set_title('Calibration:')
				self.ax.set_ylabel('Resistance [Ohms]')
				self.ax.set_xlabel('Time [s]')

				#path = os.path.join(self.cwd, 'cali.out')
				path = self.filePath
				with open(path, 'r') as file:
					for line in file.read().splitlines()[2:]:
						data = [float(x) for x in line.split(',')]
						xdata = data[5]
						ydata = data[4]
						# Add single data point:
						self.ax.plot(xdata, ydata, c='tab:red', marker='o')
				self.fig.canvas.draw()

				self.dataShowing = 'calibrationData'
				self.dataToSave = 'calibrationData'

		elif function == 'continuous':
			if self.dataShowing == 'continuousData':
				xdata = self.latestDataPoint[9]
				ydata = self.latestDataPoint[4]
				# Add single data point:
				self.ax.plot(xdata, ydata, c='tab:green', marker='o')
				self.fig.canvas.draw()
			else:
				self.ax.clear()
				self.ax.set_title('Continuous measurement:')
				self.ax.set_ylabel('Resistance [Ohms]')
				self.ax.set_xlabel('Time [s]')

				#path = os.path.join(self.cwd, 'conti.out')
				path = self.filePath
				with open(path, 'r') as file:
					for line in file.read().splitlines()[2:]:
						data = [float(x) for x in line.split(',')]
						xdata = data[9]
						ydata = data[4]
						# Add single data point:
						self.ax.plot(xdata, ydata, c='tab:green', marker='o')
				self.fig.canvas.draw()

				self.dataShowing = 'continuousData'
				self.dataToSave = 'continuousData'

		elif function == 'IVcurve':
			if self.dataShowing == 'IVcurveData':
				xdata = self.latestDataPoint[2]
				ydata = self.latestDataPoint[3]
				# Add single data point:
				self.ax.plot(xdata, ydata, c='tab:red', marker='o')
				self.fig.canvas.draw()
			else:
				self.ax.clear()
				self.ax.set_title('I-V curve:')
				self.ax.set_xlabel('Voltage [V]')
				self.ax.set_ylabel('Current [A]')

				#path = os.path.join(self.cwd, 'IVcurve.out')
				path = self.filePath
				with open(path, 'r') as file:
					for line in file.read().splitlines()[2:]:
						data = [float(x) for x in line.split(',')]
						xdata = data[2]
						ydata = data[3]
						# Add single data point:
						self.ax.plot(xdata, ydata, c='tab:red', marker='o')
				self.fig.canvas.draw()

				self.dataShowing = 'IVcurveData'
				self.dataToSave = 'IVcurveData'

	def _temperatureRun_takeMeas(self):
		""" Initiates n measurements, updates data file and plot.
		"""
		# Number of measurements over which to average:
		n = 15
		U, R, U_source, I_source, R_source = self.URUIR(n=n, deltaMode=1)
		# Resistance standard deviation:
		DR = R.std()
		try:
			U = sum(U) / n
			R = sum(R) / n
			U_source = sum(U_source) / n
			I_source = sum(I_source) / n
			R_source = sum(R_source) / n
		except TypeError:
			pass
		print "Resistance at {} K = {} Ohms. Spread = {} %.".format(self.T_sample, R, abs(DR/R))

		# When adding columns to the output data table, please
		# adjust the data variable below as well as the
		# self.DataHead array in the temperature(Auto)Run function.
		data = np.array([self.T_sample, self.T_cryo, self.I, U, R, DR, U_source, I_source, R_source, time.time()])
		self.latestDataPoint = data

		self.Head = np.array([["T_sample", "T_cryo", "U_setpoint", "U_sample", "R_sample", "DR", "U_source",
							   "I_source", "R_source", "t"],
							  ["K", "K", "V", "V", "Ohms", "Ohms", "V", "A", "Ohms", "s"]])

		#path = os.path.join(self.cwd, 'temp.out')
		path = self.filePath
		if not os.path.isfile(path):
			with open(path, 'w') as file:
				for line in self.Head:
					string = self.delimiter.join(str(x) for x in line)
					file.write(string + '\n')
		with open(path, 'a') as file:
			data_string = self.delimiter.join(str(x) for x in data)
			file.write(data_string+'\n')

		#self._temperatureAutoRunNew_updatePlot(function='measure')
		while self.plot_request_flag:
			# wait for previous plot call to finish
			time.sleep(0.01)
		self.plot_request_function = 'measure'
		self.plot_request_flag = 1

	def _temperatureRun_continuousMeas(self, plot=0, n=1):
		""" Continuously measures resistance until interrupted.
		:param plot: Boolean to determine whether to self.updatePlot
		:param n : Number of measurements over which to average
		"""
		self.ContiHead = np.array([["T_sample", "T_cryo", "I_setpoint", "U_sample", "R_sample", "DR", "U_source", "I_source", "R_source", "t"],
							 ["K", "K", "A", "V", "Ohms", "Ohms", "V", "A", "Ohms", "s"]])

		self.K2401.write(":OUTP ON")
		t0 = time.time()

		#path = os.path.join(self.cwd, 'conti.out')
		path = self.filePath
		with open(path, 'w') as file:
			for line in self.ContiHead:
				string = self.delimiter.join(str(x) for x in line)
				file.write(string + '\n')
		while (self.stopFlag == 0) and (self.stopContinuousFlag == 0):
			#self.K2401.write(":OUTP ON")
			t = time.time() - t0

			U, R, U_source, I_source, R_source = self.URUIR(n=n, deltaMode=1)
			# Resistance standard deviation:
			DR = 0
			if n > 1:
				DR = R.std()
				U = sum(U) / n
				R = sum(R) / n
				U_source = sum(U_sample) / n
				I_source = sum(I_source) / n
				R_source = sum(R_source) / n

			if self.use_cryo:
				self.cryostat.updateStatus()
				self.T_cryo = self.cryostat.cryoTemp
				self.T_sample = self.cryostat.sampleTemp

			data = np.array([self.T_sample,self.T_cryo, self.I, U, R, DR, U_source, I_source, R_source, t])
			self.latestDataPoint = data

			data_string = self.delimiter.join(str(x) for x in data)

			with open(path, 'a') as file:
				file.write(data_string + '\n')

			if plot:
				#self._temperatureAutoRunNew_updatePlot(function='continuous')
				while self.plot_request_flag:
					# wait for previous plot call to finish
					time.sleep(0.01)
				self.plot_request_function = 'continuous'
				self.plot_request_flag = 1
			#self.K2401.write(":OUTP OFF")
			#time.sleep(60)
			#if t >= 5*60*60:
			#	break

		self.K2401.write(":OUTP OFF")

	def _temperatureRun_startContinuous(self):
		""" Callback function for the 'Continuous' button.
		Starts new thread for continuous measurement function.
		"""
		if self.continuousActive:
			try:
				self._temperatureAutoRun_updateStatus()
			except AttributeError:
				pass
			self.stopContinuousFlag = 1
			self.continuousActive = 0
			self.contiVar.set('Start continuous')
		elif not self.continuousActive:
			t = 'Overwrite log file?'
			m = 'The log file already exists. Do you wish to overwrite it?'
			if os.path.exists(self.filePath) and not tkMessageBox.askokcancel(t, m):
				pass
			else:
				try:
					self._temperatureAutoRun_updateStatus('continuous measurement...', 1)
				except AttributeError:
					pass
				#self._temperatureAutoRunNew_updatePlot(function='clear13')
				while self.plot_request_flag:
					# wait for previous plot call to finish
					time.sleep(0.01)
				self.plot_request_function = 'clear13'
				self.plot_request_flag = 1

				self.stopFlag = 0
				self.stopContinuousFlag = 0
				target = self._temperatureRun_continuousMeas
				# plotting enabled: args = (1,)
				plotbool = 1
				#title = 'Enable plotting?'
				#message = 'Would you like to enable live plotting? (Can cause instability with long measurements)'
				#plotbool = tkMessageBox.askyesno(title, message)
				args = (plotbool,)
				self.measurement = Thread(target=target, args=args)
				self.measurement.start()
				self.continuousActive = 1
				self.contiVar.set('Stop continuous')
				self.dataShowing = ''
				self.dataToSave = 'continuousData'

	def _temperatureRun_updateT(self, event):
		""" Textbox callback function to update Temperature. Checks only
		if input is float like.
		"""
		try:
			self.T_sample = float(event)
		except:
			pass

	def _temperatureRun_updateLimit(self, event):
		""" Textbox callback function to update limit of measurement
		spread. Checks only if input is float-like.
		"""
		try:
			self.limit = float(event)
		except:
			pass

	def _temperatureRun_updateI_userInput(self, event):
		""" Textbox callback function to update current, checks only if
		input is float-like.
		"""
		try:
			self.I_userInput = float(event)
		except:
			print "Please enter valid current!"

	def _temperatureRun_updateI(self, event):
		""" Enables manual change of the K2401 current setpoint by user,
		if requested value is within limits.
		"""
		if abs(self.I_userInput) > self.I_max:
			print "Maximum allowed current I_max = {} A.".format(self.I_max)
			self.I = np.sign(self.I_userInput)*self.I_max
			self.t2.set_val(self.I)
		elif abs(self.I_userInput) < self.I_min:
			print "Minimum possible current I_min = {} A.".format(self.I_min)
			self.I = np.sign(self.I_userInput)*self.I_min
			self.t2.set_val(self.I)
		else:
			print "Current updated to {} A.".format(self.I_userInput)
			self.I = self.I_userInput
		self.K2401.write(":SOUR:CURR:RANG {:.2e}".format(self.I))
		self.K2401.write(":SOUR:CURR:LEV {:.2e}".format(self.I))
		self.t2.set_val(self.I)

	def _temperatureRun_calibrate(self):
		""" Calls calibration function self.calibrate() upon button
		press, updates textbox.
		"""
		if self.calibrateActive:
			try:
				self._temperatureAutoRun_updateStatus()
			except AttributeError:
				pass
			plt.draw()
			self.stopFlag = 1
			self.calibrateActive = 0
			self.b0.color = 'lightgray'
			self.b0.hovercolor = 'lightskyblue'
			self.b0.label.set_text('Calibrate I')
		elif not self.calibrateActive:
			t = 'Overwrite log file?'
			m = 'The log file already exists. Do you wish to overwrite it?'
			if os.path.exists(self.filePath) and not tkMessageBox.askokcancel(t, m):
				pass
			else:
				#self._temperatureAutoRunNew_updatePlot(function='clear24')
				while self.plot_request_flag:
					# wait for previous plot call to finish
					time.sleep(0.01)
				self.plot_request_function = 'clear24'
				self.plot_request_flag = 1

				# DIALOG NOCH VERBESSERN #######################################
				if tkMessageBox.askyesno(title='I-V', message='I(V) instead of R(I)?'):
					try:
						self._temperatureAutoRun_updateStatus('calibrating...', 1)
					except AttributeError:
						pass
					plt.draw()
					self.stopFlag = 0
					target = self.IVcurve
					args = (10, 2, 0.0, 1)
					self.calibration = Thread(target=target, args=args)
					self.calibration.start()
					self.calibrateActive = 1
					self.b0.color = 'lightskyblue'
					self.b0.hovercolor = 'lightgray'
					self.b0.label.set_text('Stop')
					self.dataShowing = ''
					self.dataToSave = 'IVcurveData'
				else:
					try:
						self._temperatureAutoRun_updateStatus('calibrating...', 1)
					except AttributeError:
						pass
					plt.draw()
					self.stopFlag = 0
					target = self.calibrate
					args = (10, 2, 0.0, 1)
					self.calibration = Thread(target=target, args=args)
					self.calibration.start()
					self.calibrateActive = 1
					self.b0.color = 'lightskyblue'
					self.b0.hovercolor = 'lightgray'
					self.b0.label.set_text('Stop')
					self.dataShowing = ''
					self.dataToSave = 'calibrationData'
					self.t2.set_val(self.I)

	def _temperatureRun_calibrateNew(self):
		""" Calls calibration function self.calibrate() upon button
		press, updates textbox.
		"""
		if self.calibrateActive:
			try:
				self._temperatureAutoRun_updateStatus()
			except AttributeError:
				pass
			plt.draw()
			self.stopFlag = 1
			self.calibrateActive = 0
			self.caliVar.set('Calibrate')
		elif not self.calibrateActive:
			t = 'Overwrite log file?'
			m = 'The log file already exists. Do you wish to overwrite it?'
			if os.path.exists(self.filePath) and not tkMessageBox.askokcancel(t, m):
				pass
			else:
				#self._temperatureAutoRunNew_updatePlot(function='clear24')
				while self.plot_request_flag:
					# wait for previous plot call to finish
					time.sleep(0.01)
				self.plot_request_function = 'clear24'
				self.plot_request_flag = 1

				self._temperatureAutoRun_updateStatus('calibrating...', 1)
				self.stopFlag = 0
				target = self.calibrateNew
				args = (10, 2, 0.0, 1)
				self.calibration = Thread(target=target, args=args)
				self.calibration.start()
				self.calibrateActive = 1
				self.caliVar.set('Stop calibration')
				self.dataShowing = ''
				self.dataToSave = 'calibrationData'

	def _temperatureRun_saveFile(self, event):
		""" Opens dialog to save DataTable to .csv file.
		"""
		dstn_path = 0
		if self.dataToSave:
			ftypes = [('CSV files', 'csv'), ('All files', '*')]
			dstn_path = tkFileDialog.asksaveasfilename(filetypes=ftypes,
													  defaultextension='.csv')

		if dstn_path:
			if self.dataToSave == 'measurementData':
				src_path = os.path.join(self.cwd, 'temp.out')
			elif self.dataToSave == 'calibrationData':
				src_path = os.path.join(self.cwd, 'cali.out')
			elif self.dataToSave == 'continuousData':
				src_path = os.path.join(self.cwd, 'conti.out')
			elif self.dataToSave == 'IVcurveData':
				src_path = os.path.join(self.cwd, 'IVcurve.out')

			# Copy appropriate temporary file to new location
			with open(src_path, 'r') as src, open(dstn_path, 'w') as dstn:
				dstn.write(src.read())
			print "File saved to {}.".format(dstn_path)

	def _temperatureRun_exit(self):
		""" Ask user confirmation to exit measurement, then remove
		temporary data and/or close CryoConnector, as applicable.
		"""
		if tkMessageBox.askokcancel('Exit Measurement', 'Are you sure you want to exit the current Measurement?'):
			self.stopFlag = 1
			try:
				os.remove(os.path.join(self.cwd, 'temp.out'))
			except WindowsError:
				pass

			try:
				self.cryostat.CryoConnector.kill()
			except AttributeError:
				pass

			self.mainWindow.withdraw()
			self.mainWindow.destroy()
			self.exitFlag = 1
			#plt.close()

	def _temperatureRun_clearLast(self, event):
		""" Ask user confirmation, then clear last entry in current
		file and update plot.
		"""
		if tkMessageBox.askokcancel('Clear last', 'Clear last data point?'):
			if self.dataShowing == 'measurementData':
				path = os.path.join(self.cwd, 'temp.out')
				function = 'measure'
			elif self.dataShowing == 'continuousData':
				path = os.path.join(self.cwd, 'conti.out')
				function = 'continuous'
			elif self.dataShowing == 'calibrationData':
				path = os.path.join(self.cwd, 'cali.out')
				function = 'calibrate'
			else:
				raise Exception
			with open(path, "r+") as file:		# encoding = "utf-8" ?

				# Move the pointer to the end of the file:
				file.seek(0, os.SEEK_END)

				# This code means the following code skips the last two
				# character in the file - i.e. in the case the last line
				# is null we delete the last line & the penultimate one.
				pos = file.tell() - 2

				# Read each character in the file one at a time from the
				# penultimate character going backwards, searching for a
				# newline character. If we find a new line, exit search.
				while pos > 0 and file.read(1) != "\n":
					pos -= 1
					file.seek(pos, os.SEEK_SET)

				# So long as we're not at the start of the file, delete
				# all the characters ahead of this position.
				if pos > 0:
					file.seek(pos+1, os.SEEK_SET)
					file.truncate()

				# Re-add newline charakter at the end of the file.
				#file.write('\n')
			self.dataShowing = ''
			self._temperatureRun_updatePlot(function)

	def _temperatureRun_clearAll(self, event):
		""" Ask user confirmation, then clear current data file, update
		plot.
		"""
		if tkMessageBox.askokcancel('Clear all', 'Clear all data points?'):
			if self.dataShowing == 'measurementData':
				path = os.path.join(self.cwd, 'temp.out')
				function = 'measure'
				head = self.DataHead
			elif self.dataShowing == 'calibrationData':
				path = os.path.join(self.cwd, 'cali.out')
				function = 'calibrate'
				head = self.CaliHead
			elif self.dataShowing == 'continuousData':
				path = os.path.join(self.cwd, 'conti.out')
				function = 'continuous'
				head = self.ContiHead
			else:
				raise Exception
			with open(path, 'w') as file:
				for line in head:
					string = self.delimiter.join(str(x) for x in line)
					file.write(string + '\n')
			self.dataShowing = ''
			self._temperatureRun_updatePlot(function=function)

	def _temperatureRun_stopButton(self, event):
		""" Callback function for the stop button, which raises the stop
		flag via the stop() function. """
		if self.stopButtonActive:
			self.stop()
			self.stopButtonActive = 0
			self._temperatureAutoRun_updateStopButton()

	def _addButton(self):
		""" Callback function for the button to add a stage to the measurement program.
		"""
		try:
			values = [float(e.get()) for e in self.entries]
			if self.use_apex:
				values.append(self.variable.get())
			row_id = self.tree.focus()
			if row_id:
				self.tree.insert('', self.tree.index(row_id)+1, values=values)
			else:
				self.tree.insert('', 'end', values=values)
			return 0
		except ValueError:
			print 'Please enter valid values!'
			return 1

	def _okayButton(self):
		""" Callback function for the okay button.
		"""
		error = self._addButton()
		if not error:
			self.addStageWindow.destroy()

	def _closeButton(self):
		""" Callback function for the close button.
		"""
		self.addStageWindow.destroy()

	def _addStage(self):
		""" Callback function for add stage button, opens submenu.
		"""
		self.addStageWindow = tk.Toplevel(master=self.configWindow)
		self.addStageWindow.title('Add stage')

		self.variable = tk.StringVar()
		self.variable.set(self.XRDlist[0])

		self.label0 = tk.Label(self.addStageWindow, text='Please enter:')
		self.label0.grid(row=1, column=0)

		self.labels = []
		self.entries = []
		i = 0
		for text in self.columns:
			if not text == 'XRD sweep':
				self.labels.append(tk.Label(self.addStageWindow, text=text))
				self.entries.append(tk.Entry(self.addStageWindow))
				self.labels[i].grid(row=0, column=i+1)
				self.entries[i].grid(row=1, column=i+1)
				i = i+1
			else:
				self.labelx = tk.Label(self.addStageWindow, text=text)
				self.labelx.grid(row=0, column=i+1)
				self.menu = tk.OptionMenu(self.addStageWindow, self.variable, *self.XRDlist)	# need * to pass as list
				self.menu.grid(row=1, column=i+1)

		ccb1 = tk.Button(self.addStageWindow, text='Add', command=self._addButton)
		ccb1.grid(row=2, column=i, sticky='E')

		ccb2 = tk.Button(self.addStageWindow, text='Close', command=self._closeButton)
		ccb2.grid(row=2, column=i+1, sticky='EW')

	def _deleteStage(self):
		""" Callback function for the delete stage button.
		"""
		selection = self.tree.selection()
		if selection:
			for row_id in selection:
				self.tree.delete(row_id)
		else:
			print 'Nothing selected.'

	def _moveUp(self):
		""" Callback function to move element up in tree.
		"""
		row_id = self.tree.focus()
		if row_id:
			self.tree.move(row_id, self.tree.parent(row_id), self.tree.index(row_id)-1)

	def _moveDown(self):
		""" Callback function to move element down in tree.
		"""
		row_id = self.tree.focus()
		if row_id:
			self.tree.move(row_id, self.tree.parent(row_id), self.tree.index(row_id)+1)

	def _configureXrayScans(self):
		""" Not implemented.
		"""
		pass

	def _closeConfigWindow(self):
		""" Callback function for OK button. Saves list of stages and
		closes the window.
		"""
		self.stageList = []
		for child in self.tree.get_children():
			string_values = self.tree.item(child)["values"]
			float_values = [float(value) for value in string_values]
			self.stageList.append(float_values)
		path = os.path.join(self.cwd, 'stageList.out')
		np.savetxt(path, self.stageList, fmt='%s') #, fmt='%s'
		self.configWindow.destroy()

	def _temperatureAutoRun_configureRun(self):
		""" Callback function for configure run button. Tries to load
		previously saved configuration, opens submenu.
		"""
		# Try loading previously configured run.
		if os.path.isfile(os.path.join(self.cwd, 'stageList.out')):
			try:
				stageArray = np.genfromtxt(os.path.join(self.cwd, 'stageList.out'), dtype=float)
				self.stageList = stageArray.tolist()
			except UserWarning:
				pass

		# Configure Tkinter window.
		self.configWindow = tk.Toplevel(master=self.mainWindow)
		self.configWindow.title('Configure measurement run')

		# Configure treeview and initiate iid (item id) as 0.
		if self.use_apex:
			self.columns = ('Target temperature [K]',
							'Cooling rate [K/min]',
							'Step width [K]',
							'Wait before measure [min]',
							'XRD sweep')
		else:
			self.columns = ('Target temperature [K]',
							'Cooling rate [K/min]',
							'Step width [K]',
							'Wait before measure [min]')
		self.tree = ttk.Treeview(self.configWindow, columns=self.columns)
		self.tree['show'] = 'headings'

		for row in self.stageList:
			self.tree.insert('', 'end', values=row)

		self.tree.heading('#0', text='#')
		self.tree.column('#0', width=60, minwidth=60)
		for text in self.columns:
			self.tree.heading(text, text=text)
			self.tree.column(text, width=150, minwidth=150)

		self.tree.grid(row=0, column=0, rowspan=3, columnspan=3)

		cb0 = tk.Button(self.configWindow, text='Add stage', command=self._addStage)
		cb0.grid(row=4, column=0, sticky='EW')

		cb1 = tk.Button(self.configWindow, text='Delete Stage', command=self._deleteStage)
		cb1.grid(row=5, column=0, sticky='EW')

		cb2 = tk.Button(self.configWindow, text='Move up', command=self._moveUp)
		cb2.grid(row=4, column=1, sticky='EW')

		cb3 = tk.Button(self.configWindow, text='Move down', command=self._moveDown)
		cb3.grid(row=5, column=1, sticky='EW')

		if self.use_apex:
			cb4 = tk.Button(self.configWindow, text='Configure X-Ray scans', command=self._configureXrayScans)
			cb4.grid(row=4, column=2, sticky='EW')

		cb5 = tk.Button(self.configWindow, text='OK', command=self._closeConfigWindow)
		cb5.grid(row=5, column=2, sticky='EW')

		self.configWindow.mainloop()

	def _temperatureAutoRun_takeMeas(self):
		""" Successively performs stages of the user-configured
		measurement run. """

		self.dataToSave = 'measurementData'

		# Initiate empty arrays for temperature steps and associated
		# ramp rates and step_widths of all stages:
		program_steps = np.array([])
		program_ramp_rates = np.array([])
		program_step_widths = np.array([])
		program_wait_minutes = np.array([])

		# Initiate time for one resistance measurement in seconds:
		R_probe_time = 10

		# starting_temperature for first stage is current temperature:
		self.cryostat.updateStatus()
		starting_temperature = self.cryostat.sampleTemp

		for stage_parameters in self.stageList:
			final_target_temperature = stage_parameters[0]
			stage_ramp_rate = stage_parameters[1]
			step_width_input = stage_parameters[2]
			wait_minutes = stage_parameters[3]
			wait_seconds = 60 * wait_minutes

			step_width_abs = abs(step_width_input)
			step_width = np.sign(final_target_temperature -
								 starting_temperature) * step_width_abs

			# Create list of intermediate temperature setpoints (steps)
			# inverted, so that start is half-open, rather than stop:
			steps_inverted = np.arange(start=final_target_temperature,
									   stop=starting_temperature,
									   step=(-1)*step_width)

			# Flip list of steps:
			steps = np.flip(steps_inverted)

			# Create arrays of ramp rates and step widths for each step:
			# (step_widths is only used for estimate of total duration)
			ramp_rates = stage_ramp_rate * np.ones(len(steps))
			step_widths = step_width_abs * np.ones(len(steps))
			wait_minutess = wait_minutes * np.ones(len(steps))

			# Append steps, ramp rates and step_widths to program:
			program_steps = np.append(program_steps, steps)
			program_ramp_rates = np.append(program_ramp_rates, ramp_rates)
			program_step_widths = np.append(program_step_widths, step_widths)
			program_wait_minutes = np.append(program_wait_minutes, wait_minutess)

			# starting_temperature for next stage is final setpoint
			# of this stage:
			starting_temperature = final_target_temperature

		# Avoid division by zero in t_to_completion calculation:
		program_ramp_rates_nonzero = program_ramp_rates
		for i in range(len(program_ramp_rates_nonzero)):
			if program_ramp_rates_nonzero[i] == 0:
				program_ramp_rates_nonzero[i] = 1000

		t_start = time.time()
		for i in range(len(program_steps)):
			if self.stopFlag:
				break
			t_elapsed = time.time() - t_start

			# Calculating estimate of remaining time in program:
			ramping_duration = sum(abs(program_step_widths[i:]) / abs(program_ramp_rates_nonzero[i:]) * 60)
			waiting_duration = sum(abs(program_wait_minutes[i:])) * 60
			measuring_duration = R_probe_time * len(program_steps[i:])
			t_to_completion = sum([ramping_duration,
									   waiting_duration,
									   measuring_duration])
			t_of_arrival = time.time() + t_to_completion
			days_elapsed = int(t_elapsed/(60*60*24))
			days_to_completion = int(t_to_completion/(60*60*24))

			# Convert times to formatted strings:
			te = time.strftime('%H:%M:%S', time.gmtime(t_elapsed))
			etc = time.strftime('%H:%M:%S', time.gmtime(t_to_completion))
			eta = time.strftime('%b %d %Y %H:%M:%S', time.gmtime(t_of_arrival)) # time zone wrong

			# Print to console:
			if bool(days_elapsed):
				print 'Elapsed: {} days {} hours'.format(days_elapsed, te)
			else:
				print 'Elapsed: {} hours'.format(te)
			if bool(days_to_completion):
				print 'Estimated time to completion: {} days {} hours\n'.format(days_to_completion, etc)
			else:
				print 'Estimated time to completion: {} hours\n'.format(etc)
			#print 'Started: {}\nEstimated time of completion: {}\n'.format(t_start, eta)

			# Send ramp command to temperature controller:
			self.cryostat.ramp(program_ramp_rates[i], program_steps[i])
			time.sleep(1)
			self.cryostat.updateStatus()

			# Wait for completion of setpoint ramping:
			while self.cryostat.phaseStatus == 'Ramp':
				if self.stopFlag:
					break
				message = ', '.join([self.cryostat.deviceStatus,
									self.cryostat.phaseStatus,
									self.cryostat.alarmStatus])
				if self.cryostat.alarmLevel == 0:
					showcolor = 1
				else:
					showcolor = self.cryostat.alarmLevel

				# Update the status message bar:
				self._temperatureAutoRun_updateStatus(message, showcolor)
				plt.draw()

				if self.cryostat.alarmLevel >= 2:
					self.stopFlag = 1
				if self.stopFlag:
					break
				else:
					time.sleep(1)
					self.cryostat.updateStatus()

			# Wait for temperature to settle before probing resistance:
			t_wait_start = time.time()
			t_waiting = 0
			self.cryostat.updateStatus()
			while t_waiting < 60*program_wait_minutes[i]:
				if self.stopFlag:
					break
				wait_remaining = 60*program_wait_minutes[i] - t_waiting
				wr = time.strftime('%H:%M:%S', time.gmtime(wait_remaining))
				message = ', '.join(['Waiting... -{}'.format(wr),
									self.cryostat.alarmStatus])
				if self.cryostat.alarmLevel == 0:
					showcolor = 1
				else:
					showcolor = self.cryostat.alarmLevel

				# Update the status message bar:
				self._temperatureAutoRun_updateStatus(message, showcolor)
				plt.draw()

				if self.cryostat.alarmLevel >= 2:
					self.stopFlag = 1
				if self.stopFlag:
					break
				else:
					time.sleep(1)
					self.cryostat.updateStatus()
					t_waiting = time.time() - t_wait_start

			# Measure resistance:
			if not self.stopFlag:
				message = 'Measuring resistance...'
				showcolor = 1
				self._temperatureAutoRun_updateStatus(message, showcolor)
				plt.draw()

				self.T_cryo = self.cryostat.cryoTemp
				self.T_sample = self.cryostat.sampleTemp

				t_probe_start = time.time()

				# Take measurement of resistance, write to file:
				self._temperatureRun_takeMeas(event=None)

				# Update time it takes to take one measurement for
				# estimate of t_to_completion (moving)
				new = time.time() - t_probe_start
				R_probe_time = np.mean([new, R_probe_time])

		self.cryostat.updateStatus()
		if self.stopFlag:
			message = ', '.join(['Stopped',
								 self.cryostat.alarmStatus])
			self._temperatureAutoRun_updateStatus(message=message, showcolor=self.cryostat.alarmLevel)
			self.stopButtonActive = self._temperatureAutoRun_updateStopButton('OFF')
			plt.draw()
			if bool(self.cryostat.alarmLevel):
				self.cryostat.stop()
		else:
			message = ', '.join(['Measurement complete',
								 self.cryostat.alarmStatus])
			self._temperatureAutoRun_updateStatus(message=message, showcolor=self.cryostat.alarmLevel)
			self.stopButtonActive = self._temperatureAutoRun_updateStopButton('OFF')
			plt.draw()

	def _temperatureAutoRun_updateStatus(self, message='ready...', showcolor=0):
		""" Updates the status message bar with a message and color
		change. For the showcolor parameter:
		0 is white,
		1 is green,
		2 is yellow,
		3 is orange,
		4 is red,
		and everything else means no change.
		"""
		if showcolor == 0:
			# white
			self.statusBar.config(bg='white')
		elif showcolor == 1:
			# green
			self.statusBar.config(bg='#C8F7C8')
		elif showcolor == 2:
			# yellow
			self.statusBar.config(bg='#F7F7C8')
		elif showcolor == 3:
			# orange
			self.statusBar.config(bg='#F7D7B7')
		elif showcolor == 4:
			# red
			self.statusBar.config(bg='#F7B7B7')

		self.statusMessage.set(message)

	def _temperatureAutoRun_updateStopButton(self, setTo='OFF'):
		""" Activates/deactivates the STOP button functionality,
		returns 1/0 for the self.stopButtonActive status variable.
		"""
		if setTo == 'ON':
			self.mb5.config(state='normal')
			return 1
		if setTo == 'OFF':
			self.mb5.config(state='disabled')
			return 0

	def _temperatureAutoRun_start(self):
		""" Callback function for the START button. Starts the
		user-configured measurement run in a new thread.
		"""
		t = 'Overwrite log file?'
		m = 'The log file already exists. Do you wish to overwrite it?'
		if os.path.exists(self.filePath) and not tkMessageBox.askokcancel(t, m):
			pass
		else:
			#self._temperatureAutoRunNew_updatePlot(function='clear13')
			while self.plot_request_flag:
				# wait for previous plot call to finish
				time.sleep(0.01)
			self.plot_request_function = 'clear13'
			self.plot_request_flag = 1

			self._temperatureAutoRun_updateStatus('starting...', 1)
			self.stopButtonActive = self._temperatureAutoRun_updateStopButton('ON')
			self.stopFlag = 0
			self.measurement = Thread(target=self._temperatureAutoRun_takeMeas)
			self.measurement.start()

	def _temperatureAutoRun_rampDialogCancel(self):
		""" Cancel button callback function"""
		self.rampDialog.destroy()
		self.rampDialogOutput = ('', '')

	def _temperatureAutoRun_rampDialogOk(self):
		""" Ok button callback function"""
		self.rampDialogOutput = (self.rampEntry.get(), self.tempEntry.get())
		self.rampDialog.destroy()

	def _temperatureAutoRun_rampDialog(self):
		"""
		Dialog to input ramp rate and temperature.
		:return: (rampRate, temp) or -1 if cancelled
		"""
		self.rampDialogOutput = ('', '')
		pad = 5
		self.rampDialog = tk.Toplevel(self.root)
		self.rampDialog.title('Input ramp parameters')
		self.rampDialog.resizable(0, 0)
		mainFrame = tk.Frame(self.rampDialog)
		mainFrame.pack(padx=pad, pady=pad)
		self.rampLabel = tk.Label(mainFrame, text='Ramp rate in K/min')
		self.rampLabel.grid(row=0, column=0, padx=pad, pady=pad, sticky='W')
		self.tempLabel = tk.Label(mainFrame, text='Temperature in K')
		self.tempLabel.grid(row=0, column=1, padx=pad, pady=pad, sticky='W')
		self.rampEntry = tk.Entry(mainFrame)
		self.rampEntry.grid(row=1, column=0, padx=pad, pady=pad)
		self.tempEntry = tk.Entry(mainFrame)
		self.tempEntry.grid(row=1, column=1, padx=pad, pady=pad)
		self.cancel = tk.Button(mainFrame,
								text='cancel',
								command=self._temperatureAutoRun_rampDialogCancel)
		self.cancel.grid(row=2, column=0, padx=pad, pady=pad, sticky='NSW')
		self.ok = tk.Button(mainFrame,
							text='ok',
							command=self._temperatureAutoRun_rampDialogOk)
		self.ok.grid(row=2, column=1, padx=pad, pady=pad, sticky='NES')

		self.rampDialog.wait_window()
		return self.rampDialogOutput

	def _temperatureAutoRun_ramp(self):
		"""
		Callback function for the Ramp button. Asks user to input a set-
		point temperature and ramp rate, sends ramp command to cryo.
		"""
		rampParameters = self._temperatureAutoRun_rampDialog()
		if rampParameters != ('', ''):
			self.cryostat.ramp(*rampParameters)

	def _temperatureAutoRunNew_changeFilePath(self):
		"""
		Callback function for the Name log file button.
		"""
		ftypes = [('CSV files', 'csv'), ('All files', '*')]
		dstn_path = tkFileDialog.asksaveasfilename(filetypes=ftypes,
												   defaultextension='.csv')
		if dstn_path:
			self.filePath = dstn_path
		self.filePathVar.set(self.filePath)

	def _temperatureAutoRunNew_updatePlot(self, function='measure'):
		"""
		Updates the different plots with latest data, depending on which
		function ('measure', 'continuous', 'IVcurve or 'calibrate') is
		active.	Use function 'clear13' to clear plots on the left, and
		'clear24' to clear plots on the right.
		"""

		figureSize = (4.6, 3)
		pad = 10
		tight = 0
		left = 0.20
		bottom = 0.18
		right = 1 + 0.03 - left
		top = None
		figcolor = '#FAFAFA'
		axcolor = '#FAFAFA'

		if function == 'clear13':

			self.axes1.clear()
			self.axes2.clear()
			self.axes4.clear()

			# Figure one - R(t), T(t)  - - - - - - - - - - - - - - - - -
			self.axes1.set_ylabel('Resistance [Ohms]')
			self.axes1.set_xlabel('Time [s]')
			self.axes1.grid()

			self.axes2.set_ylabel('Temperature [K]')
			self.axes2.yaxis.label.set_color('tab:blue')

			# Figure three - R(T)  - - - - - - - - - - - - - - - - - - - - -
			self.axes4.set_ylabel('Resistance [Ohms]')
			self.axes4.set_xlabel('Temperature [K]')
			self.axes4.grid()

			# Update canvases  - - - - - - - - - - - - - - - - - - - - -
			self.canvas1.draw_idle()
			#self.toolbar1.update()
			self.canvas3.draw_idle()

		if function == 'clear24':

			self.axes3.clear()
			self.axes5.clear()
			self.axes6.clear()

			# Figure two - I(V) curve  - - - - - - - - - - - - - - - - - - -
			self.axes3.set_ylabel('Current [A]')
			self.axes3.yaxis.label.set_color('tab:red')
			self.axes3.set_xlabel('Voltage [V]')
			self.axes3.set_xscale('symlog', linthreshx=2*self.U_min)
			self.axes3.set_yscale('symlog', linthreshy=200*self.I_min)
			self.axes3.grid()
			self.axes3.xaxis.grid(which='minor')  # minor grid on too
			self.axes3.yaxis.grid(which='minor')  # minor grid on too
			#plt.locator_params(axis='x', numticks=7)
			#plt.locator_params(axis='y', numticks=7)

			# Figure four - R(I), dR(I)  - - - - - - - - - - - - - - - - - -
			self.axes5.set_ylabel('Resistance [Ohms]')
			self.axes5.set_xlabel('Current [A]')
			self.axes5.set_xscale('symlog', linthreshx=200*self.I_min)
			self.axes5.grid()
			self.axes5.xaxis.grid(which='minor')  # minor grid on too
			self.axes5.yaxis.grid(which='minor')  # minor grid on too
			#plt.locator_params(axis='x', numticks=7)
			#plt.locator_params(axis='y', numticks=7)

			self.axes6.set_ylabel('Statistical uncertainty [%]')
			self.axes6.yaxis.label.set_color('tab:brown')

			# Update canvases  - - - - - - - - - - - - - - - - - - - - -
			self.canvas2.draw_idle()
			#self.toolbar2.update()
			self.canvas4.draw_idle()

		if function == 'measure' or function == 'continuous':

			xdata = self.latestDataPoint[9]
			ydata = self.latestDataPoint[4]
			self.axes1.plot(xdata, ydata, c='black', marker='o')

			ydata = self.latestDataPoint[0]
			self.axes2.plot(xdata, ydata, c='tab:blue', marker='o')

			xdata = self.latestDataPoint[0]
			ydata = self.latestDataPoint[4]
			self.axes4.plot(xdata, ydata, c='black', marker='o')

			self.canvas1.draw_idle()
			#self.toolbar1.update()
			self.canvas3.draw_idle()

		if function == 'IVcurve':

			xdata = self.latestDataPoint[0]
			ydata = self.latestDataPoint[1]
			self.axes3.plot(xdata, ydata, c='tab:red', marker='o')

			self.canvas2.draw_idle()

		elif function == 'calibrate':

			xdata = self.latestDataPoint[0]
			ydata = self.latestDataPoint[1]
			self.axes5.plot(xdata, ydata, c='black', marker='o')

			ydata = self.latestDataPoint[2]
			self.axes6.plot(xdata, ydata, c='tab:brown', marker='o')

			self.canvas4.draw_idle()

	def _temperatureAutoRunNew_configureSettingsCancel(self):
		"""
		Callback function for the cancel button, closes sub-menu window.
		"""
		self.settingsWindow.destroy()

	def _temperatureAutoRunNew_configureSettingsOk(self):
		"""
		Callback function for the Ok button, checks if user inputs are
		floats, updates corresponding values, closes window.
		"""
		self.e0.config({'background': 'white'})
		if not self.use_cryo:
			self.e12.config({'background': 'white'})
		self.e42.config({'background': 'white'})
		self.e44.config({'background': 'white'})
		self.e46.config({'background': 'white'})
		self.e52.config({'background': 'white'})
		self.e54.config({'background': 'white'})
		try:
			self.I_userInput = float(self.I_userInput_var.get())
			I_is_number = True
			I_in_limits = self.I_min <= self.I_userInput <= self.I_max
		except ValueError:
			self.e0.config({'background': '#ffc0cb'})
			I_is_number = False
			I_in_limits = False

		if not self.use_cryo:
			try:
				self.T_userInput = float(self.T_userInput_var.get())
				T_is_number = True
				T_in_limits = 0 <= self.T_userInput
			except ValueError:
				self.e12.config({'background': '#ffc0cb'})
				T_is_number = False
				T_in_limits = False
		else:
			T_is_number = True
			T_in_limits = True

		try:
			self.A_userInput = float(self.A_var.get())
			A_is_number = True
		except ValueError:
			self.e42.config({'background': '#ffc0cb'})
			A_is_number = False

		try:
			self.B_userInput = float(self.B_var.get())
			B_is_number = True
		except ValueError:
			self.e44.config({'background': '#ffc0cb'})
			B_is_number = False

		try:
			self.C_userInput = float(self.C_var.get())
			C_is_number = True
		except ValueError:
			self.e46.config({'background': '#ffc0cb'})
			C_is_number = False

		try:
			self.U_min_userInput = float(self.U_min_var.get())
			U_min_is_number = True
		except ValueError:
			self.e52.config({'background': '#ffc0cb'})
			U_min_is_number = False

		try:
			self.U_max_userInput = float(self.U_max_var.get())
			U_max_is_number = True
			if U_max_is_number:
				U_max_in_limits = self.U_max_userInput > self.U_min_userInput
			else:
				U_max_in_limits = False
		except ValueError:
			self.e54.config({'background': '#ffc0cb'})
			U_max_is_number = False
			U_max_in_limits = False

		if I_is_number and T_is_number and A_is_number and B_is_number and \
			C_is_number and U_min_is_number and U_max_is_number:
			if not (I_in_limits and T_in_limits):
				title = 'Inputs out of limits'
				message = 'Inputs were out of limits. The following changes ' \
						  'have been made:\n\n'
				if self.I_userInput < self.I_min:
					self.I_userInput = self.I_min
					self.I_userInput_var.set(str(self.I_min))
					message += 'I_setpoint to I_min ({} A)\n'.format(self.I_min)
				if self.I_userInput > self.I_max:
					self.I_userInput = self.I_max
					self.I_userInput_var.set(str(self.I_max))
					message += 'I_setpoint to I_max ({} A)\n'.format(self.I_max)
				if (not self.use_cryo) and self.T_userInput < 0.0:
					self.T_userInput = 0.0
					self.T_userInput_var.set('0')
					message += 'T to absolute zero (0 K)\n'.format(self.I_min)
				tkMessageBox.showinfo(title=title, message=message)
			self.I = self.I_userInput
			if not self.use_cryo:
				self.T_sample = self.T_userInput
				self.T_cryo = self.T_userInput
			self.A = self.A_userInput
			self.B = self.B_userInput
			self.C = self.C_userInput
			self.U_min = self.U_min_userInput
			self.U_max = self.U_max_userInput
			if self.use_cryo:
				self.calibrationCurve_TA_to_Tsample = c1 = \
					self.calibrationCurve_var_TA_to_Tsample.get()
				self.calibrationCurve_Tsample_to_TA = c2 = \
					self.calibrationCurve_var_Tsample_to_TA.get()
				self.cryostat.setCalibrationCurves(c1, c2)
			self.settingsWindow.destroy()
		else:
			title = 'Invalid inputs'
			message = 'Some of the fields contain invalid (non-float) entries.' \
					  'Please review your inputs.'
			tkMessageBox.showerror(title=title, message=message)

	def _temperatureAutoRunNew_configureSettings(self):
		"""
		Callback function for the Configure settings button, opens sub-
		menu.
		"""
		self.settingsWindow = tk.Toplevel(master=self.mainWindow)
		self.settingsWindow.geometry('490x450')
		self.settingsWindow.resizable(0, 0)
		self.settingsWindow.title('Configure measurement settings')
		pad = 5
		settingsFrame = tk.Frame(master=self.settingsWindow)
		#settingsFrame.grid(padx=pad, pady=pad)
		settingsFrame.pack(padx=pad, pady=pad)

		text = 'Change current setpoint [A]:'
		l0 = tk.Label(master=settingsFrame, text=text)
		l0.grid(row=1, column=1, padx=5, pady=5, sticky='NESW')

		subFrame0 = tk.Frame(master=settingsFrame)
		subFrame0.grid(row=2, column=1, padx=5, pady=5)

		text = 'I_setpoint = '
		l01 = tk.Label(master=subFrame0, text=text)
		l01.grid(row=0, column=0)

		self.I_userInput_var = tk.StringVar()
		self.I_userInput_var.set(np.format_float_scientific(self.I))
		self.e0 = tk.Entry(master=subFrame0, exportselection=0, width=10,
						   textvariable=self.I_userInput_var)
		self.e0.grid(row=0, column=1)

		if not self.use_cryo:
			text = 'Enter temperature [K]:'
			l1 = tk.Label(master=settingsFrame, text=text)
			l1.grid(row=3, column=1, padx=5, pady=5,
					sticky='NESW')

			subFrame1 = tk.Frame(master=settingsFrame)
			subFrame1.grid(row=4, column=1, padx=5, pady=5)

			text = 'T = '
			l11 = tk.Label(master=subFrame1, text=text)
			l11.grid(row=0, column=0)

			self.T_userInput_var = tk.StringVar()
			self.T_userInput_var.set(str(self.T_cryo))
			self.e12 = tk.Entry(master=subFrame1, exportselection=0,
						  		textvariable=self.T_userInput_var)
			self.e12.grid(row=0, column=1)

		if self.use_cryo:
			curves = [file for file in os.listdir('calibration_curves')]
			current_curves = self.cryostat.getCalibrationCurves()

			text = 'Choose temperature calibration curve (cryo -> sample):'
			l2 = tk.Label(master=settingsFrame, text=text)
			l2.grid(row=5, column=1, padx=5, pady=5,
					sticky='NESW')

			self.calibrationCurve_var_TA_to_Tsample = tk.StringVar()
			current = os.path.basename(current_curves[0])
			self.calibrationCurve_var_TA_to_Tsample.set(current)
			o2 = tk.OptionMenu(settingsFrame,
							   self.calibrationCurve_var_TA_to_Tsample,
							   *curves)
			o2.grid(row=6, column=1, padx=5, pady=5,
					sticky='NESW')

			text = 'Choose temperature calibration curve (sample -> cryo):'
			l3 = tk.Label(master=settingsFrame, text=text)
			l3.grid(row=7, column=1, padx=5, pady=5,
					sticky='NESW')

			self.calibrationCurve_var_Tsample_to_TA = tk.StringVar()
			current = os.path.basename(current_curves[1])
			self.calibrationCurve_var_Tsample_to_TA.set(current)
			o3 = tk.OptionMenu(settingsFrame,
							   self.calibrationCurve_var_Tsample_to_TA,
							   *curves)
			o3.grid(row=8, column=1, padx=5, pady=5,
					sticky='NESW')

		text = 'Change merit function weighting factors for current\n' \
			   'setpoint calibration:'
		l4 = tk.Label(master=settingsFrame, text=text)
		l4.grid(row=11, column=1, padx=5, pady=5)

		subFrame2 = tk.Frame(master=settingsFrame)
		subFrame2.grid(row=12, column=1, padx=5, pady=5)

		text = 'A = '
		l41 = tk.Label(master=subFrame2, text=text)
		l41.grid(row=0, column=0)

		self.A_var = tk.StringVar()
		self.A_var.set(str(self.A))
		self.e42 = tk.Entry(master=subFrame2, exportselection=0, width=10,
					   		textvariable=self.A_var)
		self.e42.grid(row=0, column=1)

		text = ', B = '
		l43 = tk.Label(master=subFrame2, text=text)
		l43.grid(row=0, column=2)

		self.B_var = tk.StringVar()
		self.B_var.set(str(self.B))
		self.e44 = tk.Entry(master=subFrame2, exportselection=0, width=10,
					   		textvariable=self.B_var)
		self.e44.grid(row=0, column=3)

		text = ', C = '
		l45 = tk.Label(master=subFrame2, text=text)
		l45.grid(row=0, column=4)

		self.C_var = tk.StringVar()
		self.C_var.set(str(self.C))
		self.e46 = tk.Entry(master=subFrame2, exportselection=0, width=10,
							textvariable=self.C_var)
		self.e46.grid(row=0, column=5)

		text = 'Change voltage range for current setpoint calibration [V]:'
		l5 = tk.Label(master=settingsFrame, text=text)
		l5.grid(row=13, column=1, padx=5, pady=5)

		subFrame3 = tk.Frame(master=settingsFrame)
		subFrame3.grid(row=14, column=1, padx=5, pady=5)

		text = 'U_min = '
		l51 = tk.Label(master=subFrame3, text=text)
		l51.grid(row=0, column=0)

		self.U_min_var = tk.StringVar()
		self.U_min_var.set(str(self.U_min))
		self.e52 = tk.Entry(master=subFrame3, exportselection=0, width=10,
						    textvariable=self.U_min_var)
		self.e52.grid(row=0, column=1)

		text = ', U_max = '
		l53 = tk.Label(master=subFrame3, text=text)
		l53.grid(row=0, column=2)

		self.U_max_var = tk.StringVar()
		self.U_max_var.set(str(self.U_max))
		self.e54 = tk.Entry(master=subFrame3, exportselection=0, width=10,
							textvariable=self.U_max_var)
		self.e54.grid(row=0, column=3)

		text = 'Configure automated temperature run...'
		command = self._temperatureAutoRun_configureRun
		b6 = tk.Button(master=settingsFrame, text=text, command=command)
		b6.grid(row=16, column=1, padx=5, pady=5, sticky='NESW')

		text = 'Cancel'
		command = self._temperatureAutoRunNew_configureSettingsCancel
		b71 = tk.Button(master=settingsFrame, text=text, command=command,
						width=8)
		b71.grid(row=17, column=0, padx=5, pady=5, sticky='NESW')

		text = 'OK'
		command = self._temperatureAutoRunNew_configureSettingsOk
		b72 = tk.Button(master=settingsFrame, text=text, command=command,
						width=8)
		b72.grid(row=17, column=2, padx=5, pady=5, sticky='NESW')

	def temperatureRun(self, n=20):
		""" This function initiates a manual resistance over temperature
		measurement run. The user can enter the temperature which
		the cryostat has been set to externally, then add a
		datapoint/measurement to the run.
		"""

		# When adding columns to the output data table, please adjust
		# the dataHead below as well as the data variable in the
		# _temperatureRun_takeMeas callback function.
		self.DataHead = np.array([["T_sample", "T_cryo", "I_setpoint", "U_sample", "R_sample", "DR", "U_source", "I_source", "R_source", "t"],
							 ["K", "K", "A", "V", "Ohms", "Ohms", "V", "A", "Ohms", "s"]])

		self.fig.set_figheight(6.4)
		self.fig.set_figwidth(6.4)
		self.fig.canvas.set_window_title('Manual R over T measurement')
		plt.subplots_adjust(top=0.95, bottom=0.425)
		self.ax.set_title('Current measurement run:')
		self.ax.set_ylabel('Resistance [Ohms]')
		self.ax.set_xlabel('Temperature [K]')
		self.ax.set_ylim(0, 1000)
		self.ax.set_xlim(0, 300)

		self.I_userInput = self.I

		axb0 = plt.axes([0.4, 0.25, 0.15, 0.075])
		self.b0 = Button(axb0, 'Calibrate I', hovercolor='lightskyblue')
		self.b0.on_clicked(self._temperatureRun_calibrate)

		axt0 = plt.axes([0.3, 0.25, 0.075, 0.075])
		t0 = TextBox(axt0, 'R-spread in % < ', initial=str(self.limit))
		t0.on_submit(self._temperatureRun_updateLimit)

		axb1 = plt.axes([0.4, 0.05, 0.15, 0.075])
		b1 = Button(axb1, 'Measure R', hovercolor='lightskyblue')
		b1.on_clicked(self._temperatureRun_takeMeas)

		axt1 = plt.axes([0.3, 0.05, 0.075, 0.075])
		t1 = TextBox(axt1, 'T in K = ', initial=str(self.T_sample))
		t1.on_submit(self._temperatureRun_updateT)

		axb2 = plt.axes([0.575, 0.25, 0.15, 0.075])
		b2 = Button(axb2, 'Clear last')
		b2.on_clicked(self._temperatureRun_clearLast)

		axb3 = plt.axes([0.575, 0.15, 0.15, 0.075])
		b3 = Button(axb3, 'Clear all')
		b3.on_clicked(self._temperatureRun_clearAll)

		axb4 = plt.axes([0.75, 0.25, 0.15, 0.075])
		b4 = Button(axb4, 'Save to file')
		b4.on_clicked(self._temperatureRun_saveFile)

		axb5 = plt.axes([0.75, 0.15, 0.15, 0.075])
		b5 = Button(axb5, 'Exit', hovercolor='lightcoral')
		b5.on_clicked(self._temperatureRun_exit)

		axt2 = plt.axes([0.3, 0.15, 0.075, 0.075])
		self.t2 = TextBox(axt2, 'I in A = ', initial=str(self.I_userInput))
		self.t2.on_submit(self._temperatureRun_updateI_userInput)

		axb6 = plt.axes([0.4, 0.15, 0.15, 0.075])
		b6 = Button(axb6, 'Update I')
		b6.on_clicked(self._temperatureRun_updateI)

		self.axb7 = plt.axes([0.575, 0.05, 0.15, 0.075])
		self.b7 = Button(self.axb7, 'Continuous', hovercolor='lightskyblue')
		self.b7.on_clicked(self._temperatureRun_startContinuous)

		# STOP button:
		#axb8 = plt.axes([0.75, 0.05, 0.15, 0.075])
		#self.b8 = Button(axb8, 'STOP', color='0.95')
		#self.b8.on_clicked(self._temperatureRun_stopButton)
		#self.stopButtonActive = 0

		# Check for unfinished run data, keep or overwrite temp.out:
		path = os.path.join(self.cwd, 'temp.out')
		if os.path.isfile(path):
			if tkMessageBox.askyesno('Unfinished measurement run found',
									 'Do you want to continue with the previous measurement?'):
				self._temperatureRun_updatePlot(function='measure')
			else:
				with open(path, 'w') as file:
					for line in self.DataHead:
						string = self.delimiter.join(str(x) for x in line)
						file.write(string + '\n')
		else:
			with open(path, 'w') as file:
				for line in self.DataHead:
					string = self.delimiter.join(str(x) for x in line)
					file.write(string + '\n')

		plt.show()

		# Delete files if no measurement has been performed:
		if not self.latestDataPoint.any():
			try:
				os.remove(os.path.join(self.cwd, 'temp.out'))
			except WindowsError:
				pass

	def temperatureAutoRun(self, n=20):
		""" This function scans the resistance of a connected sample
		fully automatically by incorporating remote control of supported
		cryostats via the Cryostat.py module.
		"""
		self.DataHead = np.array([["T_sample", "T_cryo", "I_setpoint", "U_sample", "R_sample", "DR", "U_source", "I_source", "R_source", "t"],
							 ["K", "K", "A", "V", "Ohms", "Ohms", "V", "A", "Ohms", "s"]])

		self.fig.set_figheight(7.4)
		self.fig.set_figwidth(6.4)

		self.fig.canvas.set_window_title('Automatic R over T measurement')

		plt.subplots_adjust(top=0.95, bottom=0.525)
		self.ax.set_title('Current measurement run:')
		self.ax.set_ylabel('Resistance [Ohms]')
		self.ax.set_xlabel('Temperature [K]')
		self.ax.set_ylim(0, 1000)
		self.ax.set_xlim(0, 300)

		self.I_userInput = self.I

		# Calibrate I button:
		axb0 = plt.axes([0.4, 0.35, 0.15, 0.075])
		self.b0 = Button(axb0, 'Calibrate I', hovercolor='lightskyblue')
		self.b0.on_clicked(self._temperatureRun_calibrate)

		# Maximum Resistance spread text input box:
		axt0 = plt.axes([0.3, 0.35, 0.075, 0.075])
		t0 = TextBox(axt0, 'R-spread in % < ', initial=str(self.limit))
		t0.on_submit(self._temperatureRun_updateLimit)

		# Configure run button:
		axb1 = plt.axes([0.125, 0.15, 0.25, 0.075])
		b1 = Button(axb1, 'Configure run')
		b1.on_clicked(self._temperatureAutoRun_configureRun)

		axb2 = plt.axes([0.575, 0.35, 0.15, 0.075])
		b2 = Button(axb2, 'Clear last')
		b2.on_clicked(self._temperatureRun_clearLast)

		axb3 = plt.axes([0.575, 0.25, 0.15, 0.075])
		b3 = Button(axb3, 'Clear all')
		b3.on_clicked(self._temperatureRun_clearAll)

		axb4 = plt.axes([0.75, 0.35, 0.15, 0.075])
		b4 = Button(axb4, 'Save to file')
		b4.on_clicked(self._temperatureRun_saveFile)

		axb5 = plt.axes([0.75, 0.25, 0.15, 0.075])
		b5 = Button(axb5, 'Exit', hovercolor='lightcoral')
		b5.on_clicked(self._temperatureRun_exit)

		axt2 = plt.axes([0.3, 0.25, 0.075, 0.075])
		self.t2 = TextBox(axt2, 'I in A = ', initial=str(self.I_userInput))
		self.t2.on_submit(self._temperatureRun_updateI_userInput)

		axb6 = plt.axes([0.4, 0.25, 0.15, 0.075])
		b6 = Button(axb6, 'Update I')
		b6.on_clicked(self._temperatureRun_updateI)

		axb7 = plt.axes([0.4, 0.15, 0.15, 0.075])
		b7 = Button(axb7, 'Start run', hovercolor='lightskyblue')
		b7.on_clicked(self._temperatureAutoRun_start)

		self.axb7 = plt.axes([0.575, 0.15, 0.15, 0.075])
		self.b7 = Button(self.axb7, 'Continuous', hovercolor='lightskyblue')
		self.b7.on_clicked(self._temperatureRun_startContinuous)

		# STOP button:
		axb8 = plt.axes([0.75, 0.05, 0.15, 0.075])
		self.b8 = Button(axb8, 'STOP', color='0.95')
		self.b8.on_clicked(self._temperatureRun_stopButton)
		self.stopButtonActive = 0

		# Status message box:
		axb9 = plt.axes([0.125, 0.05, 0.6, 0.075])
		self.b9 = Button(axb9, 'ready...', color='white', hovercolor='white')
		self.b9.label.set_style('italic')

		# Check for unfinished run data, keep or overwrite temp.out:
		path = os.path.join(self.cwd, 'temp.out')
		if os.path.isfile(path):
			if tkMessageBox.askyesno('Unfinished measurement run found',
									 'Do you want to continue with the previous measurement?'):
				self._temperatureRun_updatePlot(function='measure')
			else:
				with open(path, 'w') as file:
					for line in self.DataHead:
						string = self.delimiter.join(str(x) for x in line)
						file.write(string + '\n')
		else:
			with open(path, 'w') as file:
				for line in self.DataHead:
					string = self.delimiter.join(str(x) for x in line)
					file.write(string + '\n')

		plt.show()

		# Delete files if no measurement has been performed:
		if not self.latestDataPoint.any():
			try:
				os.remove(os.path.join(self.cwd, 'temp.out'))
			except WindowsError:
				pass

	def temperatureAutoRunNew(self, n=20):
		""" This function scans the resistance of a connected sample
		fully automatically by incorporating remote control of supported
		cryostats via the Cryostat.py module.
		"""
		self.DataHead = np.array([["T_sample", "T_cryo", "I_setpoint", "U_sample", "R_sample", "DR", "U_source", "I_source", "R_source", "t"],
							 ["K", "K", "A", "V", "Ohms", "Ohms", "V", "A", "Ohms", "s"]])

		date = time.strftime('%Y%m%d', time.gmtime(time.time()))
		baseName = date + '.csv'
		self.fileBasePath = os.path.join(self.cwd, baseName)
		self.filePath = self.fileBasePath

		# GUI  - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

		# Font options for embedded matplotlib canvases
		font = {'family': 'sans-serif',
				'weight': 'normal',
				'size': 8}

		plt.rc('font', **font)

		self.mainWindow = tk.Toplevel()
		self.mainWindow.withdraw()
		self.mainWindow.resizable(0, 0)
		self.mainWindow.title('Resistance Measurement')

		figureSize = (4.6, 3)
		pad = 10
		tight = 0
		left = 0.20
		bottom = 0.18
		right = 1 + 0.03 - left
		top = None
		figcolor = '#FAFAFA'
		axcolor = '#FAFAFA'

		self.mainFrame = tk.Frame(self.mainWindow)
		self.mainFrame.pack(padx=pad, pady=pad)

		# Figure one - R(t), T(t)  - - - - - - - - - - - - - - - - - - -
		self.figure1 = Figure(figureSize)
		self.axes1 = self.figure1.add_subplot(111)
		# self.axes1.set_title('Current measurement run:')
		self.axes1.set_ylabel('Resistance [Ohms]')
		self.axes1.set_xlabel('Time [s]')
		if self.use_cryo:
			self.axes1.set_ylim(0, 1000)
			self.axes1.set_xlim(0, 1)
		self.axes1.grid()

		self.axes2 = self.axes1.twinx()
		self.axes2.set_ylabel('Temperature [K]')
		self.axes2.yaxis.label.set_color('tab:blue')
		if self.use_cryo:
			self.axes2.set_ylim(0, 300)

		if tight:
			self.figure1.tight_layout()
		else:
			self.figure1.subplots_adjust(left=left,
										 bottom=bottom,
										 right=right,
										 top=top)

		self.figure1.patch.set(facecolor=figcolor)
		self.axes1.patch.set(facecolor=axcolor)

		# create canvas as matplotlib drawing area
		self.frame1 = tk.Frame(self.mainFrame, borderwidth=2, relief='sunken')
		self.canvas1 = FigureCanvasTkAgg(self.figure1, master=self.frame1)
		self.canvas1.draw()
		with warnings.catch_warnings():
			warnings.filterwarnings('ignore')
			self.toolbar1 = NavigationToolbar2TkAgg(self.canvas1, self.frame1)
			self.toolbar1.update()
		widget1 = self.canvas1.get_tk_widget()
		widget1.pack()
		self.frame1.grid(row=0, column=0, columnspan=2, padx=pad, pady=pad)

		# Figure two - I(V) curve  - - - - - - - - - - - - - - - - - - -
		self.figure2 = Figure(figureSize)
		self.axes3 = self.figure2.add_subplot(111)
		self.axes3.set_ylabel('Current [A]')
		self.axes3.yaxis.label.set_color('tab:red')
		self.axes3.set_xlabel('Voltage [V]')
		self.axes3.set_xscale('symlog', linthreshx=2*self.U_min)
		self.axes3.set_yscale('symlog', linthreshy=200*self.I_min)
		self.axes3.set_ylim(-1, 1)
		self.axes3.set_xlim(-1, 1)
		self.axes3.grid()
		self.axes3.xaxis.grid(which='minor')  # minor grid on too
		self.axes3.yaxis.grid(which='minor')  # minor grid on too

		if tight:
			self.figure2.tight_layout()
		else:
			self.figure2.subplots_adjust(left=left,
										 bottom=bottom,
										 right=right,
										 top=top)

		self.figure2.patch.set(facecolor=figcolor)
		self.axes3.patch.set(facecolor=axcolor)

		# create canvas as matplotlib drawing area
		self.frame2 = tk.Frame(self.mainFrame, borderwidth=2, relief='sunken')
		self.canvas2 = FigureCanvasTkAgg(self.figure2, master=self.frame2)
		self.canvas2.draw()
		with warnings.catch_warnings():
			warnings.filterwarnings('ignore')
			self.toolbar2 = NavigationToolbar2TkAgg(self.canvas2, self.frame2)
			self.toolbar2.update()
		widget2 = self.canvas2.get_tk_widget()
		widget2.pack()
		self.frame2.grid(row=0, column=2, columnspan=2, padx=pad, pady=pad)

		# Figure three - R(T)  - - - - - - - - - - - - - - - - - - - - -
		self.figure3 = Figure(figureSize)
		self.axes4 = self.figure3.add_subplot(111)
		self.axes4.set_ylabel('Resistance [Ohms]')
		self.axes4.set_xlabel('Temperature [K]')
		if self.use_cryo:
			self.axes4.set_ylim(0, 1000)
			self.axes4.set_xlim(0, 300)
		self.axes4.grid()

		if tight:
			self.figure3.tight_layout()
		else:
			self.figure3.subplots_adjust(left=left,
										 bottom=bottom,
										 right=right,
										 top=top)

		self.figure3.patch.set(facecolor=figcolor)
		self.axes4.patch.set(facecolor=axcolor)

		# create canvas as matplotlib drawing area
		self.frame3 = tk.Frame(self.mainFrame, borderwidth=2, relief='sunken')
		self.canvas3 = FigureCanvasTkAgg(self.figure3, master=self.frame3)
		self.canvas3.draw()
		with warnings.catch_warnings():
			warnings.filterwarnings('ignore')
			self.toolbar3 = NavigationToolbar2TkAgg(self.canvas3, self.frame3)
			self.toolbar3.update()
		widget3 = self.canvas3.get_tk_widget()
		widget3.pack()
		self.frame3.grid(row=1, column=0, columnspan=2, padx=pad, pady=pad)

		# Figure four - R(I), dR(I)  - - - - - - - - - - - - - - - - - -
		self.figure4 = Figure(figureSize)
		self.axes5 = self.figure4.add_subplot(111)
		self.axes5.set_ylabel('Resistance [Ohms]')
		self.axes5.set_xlabel('Current [A]')
		self.axes5.set_xscale('symlog', linthreshx=200*self.I_min)
		self.axes5.set_ylim(0, 1000)
		self.axes5.set_xlim(-1, 1)
		self.axes5.grid()
		self.axes5.xaxis.grid(which='minor')  # minor grid on too
		self.axes5.yaxis.grid(which='minor')  # minor grid on too

		self.axes6 = self.axes5.twinx()
		self.axes6.set_ylabel('Statistical uncertainty [%]')
		self.axes6.yaxis.label.set_color('tab:brown')
		self.axes6.set_ylim(0, 100)

		if tight:
			self.figure4.tight_layout()
		else:
			self.figure4.subplots_adjust(left=left,
										 bottom=bottom,
										 right=right,
										 top=top)

		self.figure4.patch.set(facecolor=figcolor)
		self.axes5.patch.set(facecolor=axcolor)

		# create canvas as matplotlib drawing area
		self.frame4 = tk.Frame(self.mainFrame, borderwidth=2, relief='sunken')
		self.canvas4 = FigureCanvasTkAgg(self.figure4, master=self.frame4)
		self.canvas4.draw()
		with warnings.catch_warnings():
			warnings.filterwarnings('ignore')
			self.toolbar4 = NavigationToolbar2TkAgg(self.canvas4, self.frame4)
			self.toolbar4.update()
		widget4 = self.canvas4.get_tk_widget()
		widget4.pack()
		self.frame4.grid(row=1, column=2, columnspan=2, padx=pad, pady=pad)

		# Buttons  - - - - - - - - - - - - - - - - - - - - - - - - - - -

		text = 'Configure settings'
		command = self._temperatureAutoRunNew_configureSettings
		mb0 = tk.Button(self.mainFrame, text=text, command=command)
		mb0.grid(row=2, column=0, padx=pad, pady=pad, sticky='NESW')

		text = 'Calibrate'
		self.caliVar = tk.StringVar()
		self.caliVar.set(text)
		command = self._temperatureRun_calibrateNew
		self.mb1 = tk.Button(self.mainFrame,
							 textvariable=self.caliVar,
							 command=command)
		self.mb1.grid(row=2, column=1, padx=pad, pady=pad, sticky='NESW')

		text = 'Start continuous'
		self.contiVar = tk.StringVar()
		self.contiVar.set(text)
		command = self._temperatureRun_startContinuous
		self.mb2 = tk.Button(self.mainFrame,
							 textvariable=self.contiVar,
							 command=command)
		self.mb2.grid(row=2, column=2, padx=pad, pady=pad, sticky='NESW')

		text = 'Ramp'
		command = self._temperatureAutoRun_ramp
		state = 'disabled'
		if self.use_cryo:
			state = 'normal'
		mb3 = tk.Button(self.mainFrame, text=text, command=command, state=state)
		mb3.grid(row=2, column=3, padx=pad, pady=pad, sticky='NESW')

		if self.use_cryo:
			text = 'Start configured run'
			command = self._temperatureAutoRun_start
		else:
			text = 'Take measurement'
			command = self._temperatureRun_takeMeas
		mb4 = tk.Button(self.mainFrame, text=text, command=command)
		mb4.grid(row=3, column=0, padx=pad, pady=pad, sticky='NESW')

		text = 'STOP'
		command = self.stop
		self.mb5 = tk.Button(self.mainFrame,
							 text=text,
							 command=command,
							 state='disabled')
		self.mb5.grid(row=3, column=3, padx=pad, pady=pad, sticky='NESW')

		text = 'Name log file'
		command = self._temperatureAutoRunNew_changeFilePath
		mb6 = tk.Button(self.mainFrame, text=text, command=command)
		mb6.grid(row=4, column=0, padx=pad, pady=pad, sticky='NESW')

		text = 'Exit'
		command = self._temperatureRun_exit
		mb7 = tk.Button(self.mainFrame, text=text, command=command)
		mb7.grid(row=4, column=3, padx=pad, pady=pad, sticky='NESW')

		#  Labels/messages - - - - - - - - - - - - - - - - - - - - - - -

		self.statusMessage = tk.StringVar()
		self.statusMessage.set('ready...')
		self.statusBar = tk.Label(self.mainFrame,
								  textvariable=self.statusMessage,
								  bg='white',
								  borderwidth=1,
								  relief='sunken')
		self.statusBar.grid(row=3,
							column=1,
							columnspan=2,
							padx=pad,
							pady=pad,
							sticky='NESW')

		self.filePathVar = tk.StringVar()
		self.filePathVar.set(self.fileBasePath)
		self.filePathBar = tk.Label(self.mainFrame,
									textvariable=self.filePathVar,
									borderwidth=1,
									relief='sunken')
		self.filePathBar.grid(row=4,
							  column=1,
							  columnspan=2,
							  padx=pad,
							  pady=pad,
							  sticky='NESW')

		#  - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

		self.mainWindow.protocol('WM_DELETE_WINDOW', self._temperatureRun_exit)
		self.mainWindow.deiconify()

		# The following keeps the tkinter window updating (basically
		# tk.mainloop()) but also continually checks if the diagrams
		# should be updated, which needs to be handled in the main
		# thread as the program is unstable otherwise (matplotlib is not
		# thread-safe), or if the calibration finished prompt should be
		# displayed, which also does not work from a separate thread.
		while not self.exitFlag:
			if self.plot_request_flag:
				function = self.plot_request_function
				self._temperatureAutoRunNew_updatePlot(function=function)
				self.plot_request_flag = 0

			if self.calibrationFinishedFlag:
				title = 'Calibration finished'
				part1 = 'The suggested current setpoint is I = '
				part2 = np.format_float_scientific(self.I_opt, 2)
				part3 = ' A. Do you wish to apply this setting?'
				message = part1 + part2 + part3
				if tkMessageBox.askyesno(parent=self.mainWindow,
										 title=title,
										 message=message):
					self.I = self.I_opt
				self.calibrationFinishedFlag = 0

			self.mainWindow.update_idletasks()
			self.mainWindow.update()

		self.root.destroy()

def main():

	Bi4I4 = ResistanceMeasurement(testMode=1)


if __name__ == "__main__":
	main()