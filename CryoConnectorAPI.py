import os
import getpass
import Tkinter as tk
import tkMessageBox
import ttk
import time

import xml.etree.ElementTree as ET


class CryoConnectorAPI():

	def __init__(self, workingFolder='default', port=''):
		""" :param workingFolder: Working folder of CryoConnector. Can be string, path-object or 'default'.
			:param port: Name of the port the cryostat is connected to. If empty, user is prompted to choose from a list
			of all connected devices.
		"""
		if workingFolder == 'default':
			self.cwd = os.path.join('C:', 'Users', getpass.getuser(), 'AppData', 'Roaming', 'CryoConnector', '')
		else:
			self.cwd = workingFolder				# Working folder as specified in the CryoConnector launch options
		self.active_cons = []						# List of indices of self.con_root with status 'Active'
		self.cryo_port = port						# Port the cryostat to be used is connected to.
		self.cryo_id = -1							# Index of the cryostat to be used in the connections.xml file.

		# Obtain the id of the cryostat to connect to.
		self.updateConnections()
		if not port:
			self.chooseCryo()
		else:
			for i in range(len(self.con_root)):
				if self.con_root[i].attrib.get('port') == self.cryo_port:
					if not self.con_root[i].text == 'Active':
						self.cryo_id = -2
					else:
						self.cryo_id = i
			if self.cryo_id == -1:
				raise Exception('The provided port is invalid.')
			if self.cryo_id == -2:
				raise Exception('No active device found at the provided port.')

		# Initialize cryostat
		if not self.cryo_id == -1:
			self.updateConnectionInfo()
			self.updateProperties()
			self.updateStatus()

	def updateProperties(self):
		""" Reads the [cryostat-name].xml properties file. """
		self.properties = ET.parse(self.properties_path)
		self.prop_root = self.properties.getroot()
		self.cmnd_list = self.prop_root.find('LIST_OF_COMMANDS')
		self.bttn_list = self.prop_root.find('LIST_OF_BUTTONS')
		self.phas_list = self.prop_root.find('LIST_OF_PHASES')
		self.mode_list = self.prop_root.find('LIST_OF_MODES')
		self.gas_list = self.prop_root.find('LIST_OF_GAS_TYPES')
		self.alrm_list = self.prop_root.find('LIST_OF_ALARMS')

	def updateStatus(self):
		""" Reads the status.xml file of the cryostat. """
		self.status = ET.parse(self.status_path)
		self.stat_root = self.status.getroot()
		self.prop_list = self.stat_root.find('LIST_OF_PROPERTIES')
		self.info_list = self.stat_root.find('LIST_OF_INFO')

	def get(self, name):
		""" Reads the desired property or info from the parsed status.xml object. Does not parse the file, so any data
			is only as recent as the last time self.updateStatus() was called!
			:param name: Name of the property or info item to be read. """
		result = None
		for element in self.prop_list:
			if element.attrib.get('name') == name:
				result = element.text
		if not result == None:
			return float(result)
		else:
			result = None
			for element in self.info_list:
				if element.attrib.get('name') == name:
					result = element.text
			if not result == None:
				return result
			else:
				raise Exception(r'"{}" not found. Check spelling or refer to {}.'.format(name, self.status_path))

	def updateConnectionInfo(self):
		""" Reads the connections.xml file specifically to update information on the selected cooler (self.cryo_id). """
		self.status_path = self.con_root[self.cryo_id].attrib.get('status')
		self.properties_path = self.con_root[self.cryo_id].attrib.get('properties')
		self.connectionId = self.con_root[self.cryo_id].attrib.get('id')

	def updateConnections(self):
		""" Reads the connections.xml file and checks for any 'Active' devices. Indices of these are noted in
			self.active_cons. """
		self.active_cons = []
		self.connections = ET.parse(os.path.join(self.cwd, 'connections.xml'))
		self.con_root = self.connections.getroot()

		for i in range(len(self.con_root)):
			if self.con_root[i].text == 'Active':
				self.active_cons.append(i)

	# Choose Cryostat dialog - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

	def chooseAndClose(self):
		""" Callback function for the 'OK'-button in the chooseCryo window. Gets the index of the selected cryostat in
			the connections.xml file (self.cryo_id) as well as the port (self.cryo_port) and closes the window. """
		try:
			row_id = self.tree.focus()
			if not row_id:
				# tree.focus method returns empty string when no item is selected.
				raise Exception('Nothing selected!')
			index = self.tree.index(row_id)
			self.cryo_id = self.active_cons[index]
			self.cryo_port = self.con_root[self.cryo_id].attrib.get('port')
			self.chooseWindow.destroy()
		except:
			if (__name__ == "__main__"):
				if tkMessageBox.askokcancel(title='Continue without cryostat?',
										message='No device selected! Do you wish to continue without cryostat?'):
					self.chooseWindow.destroy()
				else:
					pass
			else:
				self.chooseWindow.destroy()

	def refreshCryoList(self):
		""" Callback function for the 'Refresh'-button in the chooseCryo window. Reads connections.xml again and
			updates the treeview list. """
		self.updateConnections()
		for i in self.tree.get_children():
			self.tree.delete(i)
		for j in self.active_cons:
			self.tree.insert('', 'end', values=self.con_root[j].attrib.values())

	def chooseCryo(self):
		""" Opens GUI window for the user to select his cryostat from a list of connected devices. """
		self.chooseWindow = tk.Toplevel()
		self.chooseWindow.title('Connected devices')

		cl1 = tk.Label(self.chooseWindow, text='Please choose a cryostat from the list of connected devices below:')
		cl1.grid(row=0, column=0, columnspan=5, padx=10, pady=10)

		self.columns = self.con_root[0].attrib.keys()
		self.tree = ttk.Treeview(self.chooseWindow, columns=self.columns)
		self.tree['displaycolumns'] = ['device', 'id', 'port']
		self.tree['show'] = 'headings'

		for text in self.columns:
			self.tree.heading(text, text=text)
			self.tree.column(text, width=150, minwidth=150)
		for i in self.active_cons:
			self.tree.insert('', 'end', values=self.con_root[i].attrib.values())

		self.tree.grid(row=1, column=0, columnspan=5)

		cb0 = tk.Button(self.chooseWindow, text='OK', command=self.chooseAndClose)
		cb0.grid(row=2, column=4, padx=5, pady=5, sticky='EW')

		cb1 = tk.Button(self.chooseWindow, text='Refresh', command=self.refreshCryoList)
		cb1.grid(row=2, column=3, padx=5, pady=5, sticky='EW')

		self.tree.grid_rowconfigure(2, pad=50)

		self.chooseWindow.lift()
		self.chooseWindow.wait_window()

		if not self.cryo_port:
			raise Exception('Cryostat selection cancelled by user.')

	# Commands - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

	def command(self, name, *args):
		""" Creates an xml file in the CryoConnector working folder, which sends a command to the connected cooler.
			Please refer to the properties file of your cooler for a list of commands and their arguments.
			:param name: Name of the command as specified in the properties xml file.
			:param *args: Arguments associated with the command as specified in the properties xml file. """
		self.setp = list(args)
		self.updateProperties()
		command = 0

		# Find User input command in the properties element tree and extract the command element object.
		for subelement in self.cmnd_list:
			if subelement.attrib.get('name') == name:
				command = subelement
				params = int(command.attrib.get('params'))
				if not params == len(self.setp):
					raise Exception(r'"{}" takes exactly {} arguments ({} given)'.format(name, params, len(self.setp)))
				break
		if command == 0:
			raise Exception(r'Command "{}" not found. Check spelling or refer to {}'.format(name, self.properties_path))

		# Add connection ID and remove description element from command object.
		command.set('connection', str(self.connectionId))
		try:
			description = command.find('DESCRIPTION')
			command.remove(description)
		except:
			pass

		# Add user input values to the command object.
		msg = ['"{}" command:'.format(name)]
		for i in range(params):
			param_name = command[i].attrib.get('name')
			param_unit = command[i].attrib.get('units')

			# Check if there are discrete options given for the parameter, and if input matches one of these options.
			match = 0
			options = command[i].findall('OPTION')
			if len(options) > 0:
				for option in options:
					if float(option.attrib.get('value')) == self.setp[i]:
						match += 1
						option_text = option.text
				if not match == 1:
					raise Exception('Input does not match any of the available options. '
									'Please refer to {}'.format(self.properties_path))
				msg.append('{}: "{}" selected'.format(param_name, option_text))

			# Check if min < input < max.
			min_name = 'Min value'
			min = command[i].attrib.get('min')
			try:
				min = float(min)
			except:
				# If given as variable (string), get value by calling self.get()
				min_name = min
				min = self.get(min_name)
			max_name = "Max value"
			max = command[i].attrib.get('max')
			try:
				max = float(max)
			except:
				# If given as variable (string), get value by calling self.get()
				max_name = max
				max = self.get(max_name)

			# Add value to command object.
			if self.setp[i] < min:
				self.setp[i] = min
				msg.append('{}: Adjusted to {} = {} {}'.format(param_name, min_name, self.setp[i], param_unit))
			elif self.setp[i] > max:
				self.setp[i] = max
				msg.append('{}: Adjusted to {} = {} {}'.format(param_name, max_name, self.setp[i], param_unit))
			else:
				if not match == 1:
					msg.append('{}: Set to {} {}'.format(param_name, self.setp[i], param_unit))
			command[i].text = str(self.setp[i])

		# Print info message.
		for line in msg:
			print line

		# Write xml file.
		data = ET.tostring(command)
		with open(os.path.join(self.cwd, 'CryoConnectorAPI-command.xml'), 'w') as file:
			file.write(data)


if __name__ == "__main__":
	CC = CryoConnectorAPI()
	#CC.command('Ramp', 1039, 10)