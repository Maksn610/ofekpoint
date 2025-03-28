<script lang="ts">
	import Fuse from 'fuse.js';
	import { toast } from 'svelte-sonner';
	import { v4 as uuidv4 } from 'uuid';

	import { onMount, getContext, onDestroy, tick } from 'svelte';

	const i18n = getContext('i18n');
	const pdfjsLib = window['pdfjs-dist/build/pdf'];
	import { franc } from 'franc-min';
	import * as XLSX from 'xlsx';
	import mammoth from 'mammoth';

	pdfjsLib.GlobalWorkerOptions.workerSrc =
		'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.5.141/pdf.worker.min.js';

	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { mobile, showSidebar, knowledge as _knowledge } from '$lib/stores';

	import { updateFileDataContentById, uploadFile } from '$lib/apis/files';
	import {
		addFileToKnowledgeById,
		getKnowledgeById,
		getKnowledgeBases,
		removeFileFromKnowledgeById,
		resetKnowledgeById,
		updateFileFromKnowledgeById,
		updateKnowledgeById,
		removeDirectoryFileFromKnowledgeById
	} from '$lib/apis/knowledge';

	import { blobToFile } from '$lib/utils';

	import Spinner from '$lib/components/common/Spinner.svelte';
	import Files from './KnowledgeBase/Files.svelte';
	import AddFilesPlaceholder from '$lib/components/AddFilesPlaceholder.svelte';

	import AddContentMenu from './KnowledgeBase/AddContentMenu.svelte';
	import AddTextContentModal from './KnowledgeBase/AddTextContentModal.svelte';

	import SyncConfirmDialog from '../../common/ConfirmDialog.svelte';
	import RichTextInput from '$lib/components/common/RichTextInput.svelte';
	import Drawer from '$lib/components/common/Drawer.svelte';
	import ChevronLeft from '$lib/components/icons/ChevronLeft.svelte';
	import LockClosed from '$lib/components/icons/LockClosed.svelte';
	import AccessControlModal from '../common/AccessControlModal.svelte';
	import { WEBUI_BASE_URL } from '$lib/constants';
	import Tesseract from 'tesseract.js';

	let largeScreen = true;

	let pane;
	let showSidepanel = true;
	let minSize = 0;

	type Knowledge = {
		id: string;
		name: string;
		description: string;
		data: {
			file_ids: string[];
		};
		files: any[];
	};

	let id = null;
	let knowledge: Knowledge | null = null;
	let query = '';

	let showAddTextContentModal = false;
	let showSyncConfirmModal = false;
	let showAccessControlModal = false;

	let inputFiles = null;

	let filteredItems = [];
	let filteredDirectoryItems = [];
	let directoryFiles = { data: { metadatas: [] } };
	let fuseKnowledge;
	let fuseDirectory;

	$: if (knowledge && knowledge.files) {
		fuseKnowledge = new Fuse(knowledge.files, {
			keys: ['meta.name', 'meta.description']
		});
	}

	$: if (directoryFiles && directoryFiles.data.metadatas) {
		fuseDirectory = new Fuse(directoryFiles.data.metadatas, {
			keys: ['name']
		});
	}

	$: {
		filteredItems = query
			? (fuseKnowledge?.search(query).map((e) => e.item) ?? [])
			: (knowledge?.files ?? []);

		filteredDirectoryItems = query
			? (fuseDirectory?.search(query).map((e) => e.item) ?? [])
			: (directoryFiles?.data?.metadatas ?? []);
	}

	let selectedFile = null;
	let selectedFileId = null;

	$: if (selectedFileId) {
		const file = (knowledge?.files ?? []).find((file) => file.id === selectedFileId);
		const file1 = (directoryFiles.data.metadatas ?? []).find((file) => file.id === selectedFileId);
		const fileType = file1
			? {
				...file1,
				data: { content: file1.document_content ?? '' },
				meta: { name: file1.name }
			}
			: null;

		selectedFile = fileType ?? file ?? null;
	} else {
		selectedFile = null;
	}

	let fuse = null;
	let debounceTimeout = null;
	let mediaQuery;
	let dragged = false;

	const createFileFromText = (name, content) => {
		const blob = new Blob([content], { type: 'text/plain' });
		const file = blobToFile(blob, `${name}.txt`);

		return file;
	};

	const uploadFileHandler = async (file) => {
		const tempItemId = uuidv4();
		const fileItem = {
			type: 'file',
			file: '',
			id: null,
			url: '',
			name: file.name,
			size: file.size,
			status: 'uploading',
			error: '',
			itemId: tempItemId
		};
		if (fileItem.size == 0) {
			toast.error($i18n.t('You cannot upload an empty file.'));
			return null;
		}

		knowledge.files = [...(knowledge.files ?? []), fileItem];

		try {
			const uploadedFile = await uploadFile(localStorage.token, file).catch((e) => {
				toast.error(`${e}`);
				return null;
			});

			if (uploadedFile) {
				knowledge.files = knowledge.files.map((item) => {
					if (item.itemId === tempItemId) {
						item.id = uploadedFile.id;
					}

					// Remove temporary item id
					delete item.itemId;
					return item;
				});
				await addFileHandler(uploadedFile.id);
			} else {
				toast.error($i18n.t('Failed to upload file.'));
			}
		} catch (e) {
			toast.error(`${e}`);
		}
	};

	const uploadDirectoryHandler = async () => {
		// Check if File System Access API is supported
		const isFileSystemAccessSupported = 'showDirectoryPicker' in window;

		try {
			if (isFileSystemAccessSupported) {
				// Modern browsers (Chrome, Edge) implementation
				await handleModernBrowserUpload();
			} else {
				// Firefox fallback
				await handleFirefoxUpload();
			}
		} catch (error) {
			handleUploadError(error);
		}
	};

	// Helper function to check if a path contains hidden folders
	const hasHiddenFolder = (path) => {
		return path.split('/').some((part) => part.startsWith('.'));
	};

	// Modern browsers implementation using File System Access API
	const handleModernBrowserUpload = async () => {
		const dirHandle = await window.showDirectoryPicker();
		let totalFiles = 0;
		let uploadedFiles = 0;

		// Function to update the UI with the progress
		const updateProgress = () => {
			const percentage = (uploadedFiles / totalFiles) * 100;
			toast.info(`Upload Progress: ${uploadedFiles}/${totalFiles} (${percentage.toFixed(2)}%)`);
		};

		// Recursive function to count all files excluding hidden ones
		async function countFiles(dirHandle) {
			for await (const entry of dirHandle.values()) {
				// Skip hidden files and directories
				if (entry.name.startsWith('.')) continue;

				if (entry.kind === 'file') {
					totalFiles++;
				} else if (entry.kind === 'directory') {
					// Only process non-hidden directories
					if (!entry.name.startsWith('.')) {
						await countFiles(entry);
					}
				}
			}
		}

		// Recursive function to process directories excluding hidden files and folders
		async function processDirectory(dirHandle, path = '') {
			for await (const entry of dirHandle.values()) {
				// Skip hidden files and directories
				if (entry.name.startsWith('.')) continue;

				const entryPath = path ? `${path}/${entry.name}` : entry.name;

				// Skip if the path contains any hidden folders
				if (hasHiddenFolder(entryPath)) continue;

				if (entry.kind === 'file') {
					const file = await entry.getFile();
					const fileWithPath = new File([file], entryPath, { type: file.type });

					await uploadFileHandler(fileWithPath);
					uploadedFiles++;
					updateProgress();
				} else if (entry.kind === 'directory') {
					// Only process non-hidden directories
					if (!entry.name.startsWith('.')) {
						await processDirectory(entry, entryPath);
					}
				}
			}
		}

		await countFiles(dirHandle);
		updateProgress();

		if (totalFiles > 0) {
			await processDirectory(dirHandle);
		} else {
			console.log('No files to upload.');
		}
	};

	// Firefox fallback implementation using traditional file input
	const handleFirefoxUpload = async () => {
		return new Promise((resolve, reject) => {
			// Create hidden file input
			const input = document.createElement('input');
			input.type = 'file';
			input.webkitdirectory = true;
			input.directory = true;
			input.multiple = true;
			input.style.display = 'none';

			// Add input to DOM temporarily
			document.body.appendChild(input);

			input.onchange = async () => {
				try {
					const files = Array.from(input.files)
						// Filter out files from hidden folders
						.filter((file) => !hasHiddenFolder(file.webkitRelativePath));

					let totalFiles = files.length;
					let uploadedFiles = 0;

					// Function to update the UI with the progress
					const updateProgress = () => {
						const percentage = (uploadedFiles / totalFiles) * 100;
						toast.info(
							`Upload Progress: ${uploadedFiles}/${totalFiles} (${percentage.toFixed(2)}%)`
						);
					};

					updateProgress();

					// Process all files
					for (const file of files) {
						// Skip hidden files (additional check)
						if (!file.name.startsWith('.')) {
							const relativePath = file.webkitRelativePath || file.name;
							const fileWithPath = new File([file], relativePath, { type: file.type });

							await uploadFileHandler(fileWithPath);
							uploadedFiles++;
							updateProgress();
						}
					}

					// Clean up
					document.body.removeChild(input);
					resolve();
				} catch (error) {
					reject(error);
				}
			};

			input.onerror = (error) => {
				document.body.removeChild(input);
				reject(error);
			};

			// Trigger file picker
			input.click();
		});
	};

	// Error handler
	const handleUploadError = (error) => {
		if (error.name === 'AbortError') {
			toast.info('Directory selection was cancelled');
		} else {
			toast.error('Error accessing directory');
			console.error('Directory access error:', error);
		}
	};

	// Helper function to maintain file paths within zip
	const syncDirectoryHandler = async () => {
		if ((knowledge?.files ?? []).length > 0) {
			const res = await resetKnowledgeById(localStorage.token, id).catch((e) => {
				toast.error(`${e}`);
			});

			if (res) {
				knowledge = res;
				toast.success($i18n.t('Knowledge reset successfully.'));

				// Upload directory
				uploadDirectoryHandler();
			}
		} else {
			uploadDirectoryHandler();
		}
	};

	const addFileHandler = async (fileId) => {
		const updatedKnowledge = await addFileToKnowledgeById(localStorage.token, id, fileId).catch(
			(e) => {
				toast.error(`${e}`);
				return null;
			}
		);

		if (updatedKnowledge) {
			setTimeout(() => {
				fetchCollectionData();
			}, 2000);
			toast.success($i18n.t('File added successfully.'));
		} else {
			toast.error($i18n.t('Failed to add file.'));
			knowledge.files = knowledge.files.filter((file) => file.id !== fileId);
		}
	};

	const deleteFileHandler = async (fileId) => {
		try {
			// Remove from knowledge base only
			const updatedKnowledge = await removeFileFromKnowledgeById(localStorage.token, id, fileId);

			if (updatedKnowledge) {
				knowledge = updatedKnowledge;
				toast.success($i18n.t('File removed successfully.'));
			}
		} catch (e) {
			console.error('Error in deleteFileHandler:', e);
			toast.error(`${e}`);
		}
	};

	const getUUIDFromURL = () => {
		const pathParts = window.location.pathname.split('/');
		return pathParts[pathParts.length - 1];
	};
	const fetchCollectionData = async () => {
		const collectionId = getUUIDFromURL();

		try {
			const response = await fetch(
				`${WEBUI_BASE_URL}/api/v1/retrieval/collection/${collectionId}`,
				{
					method: 'GET',
					headers: {
						'Content-Type': 'application/json',
						authorization: 'Bearer ' + localStorage.getItem('token')
					}
				}
			);

			if (!response.ok) throw new Error(`Failed to fetch collection: ${collectionId}`);

			directoryFiles = await response.json();
		} catch (error) {
			console.error('Error fetching collection:', error);
			return null;
		}
	};

	fetchCollectionData();
	const deleteDirectoryFileHandler = async (fileId) => {
		try {
			const updatedKnowledge = await removeDirectoryFileFromKnowledgeById(
				localStorage.token,
				id,
				fileId
			);

			if (updatedKnowledge) {
				toast.success($i18n.t('File removed successfully.'));
				directoryFiles.data.metadatas = directoryFiles?.data?.metadatas?.filter(
					(file) => file?.id !== fileId
				);
			}
		} catch (e) {
			console.error('Error in deleteFileHandler:', e);
			toast.error(`${e}`);
		}
	};

	const updateFileContentHandler = async () => {
		const fileId = selectedFile.id;
		const content = selectedFile.data.content;

		const res = updateFileDataContentById(localStorage.token, fileId, content).catch((e) => {
			toast.error(`${e}`);
		});

		const updatedKnowledge = await updateFileFromKnowledgeById(
			localStorage.token,
			id,
			fileId
		).catch((e) => {
			toast.error(`${e}`);
		});

		if (res && updatedKnowledge) {
			knowledge = updatedKnowledge;
			toast.success($i18n.t('File content updated successfully.'));
		}
	};

	const changeDebounceHandler = () => {
		if (debounceTimeout) {
			clearTimeout(debounceTimeout);
		}

		debounceTimeout = setTimeout(async () => {
			if (knowledge.name.trim() === '' || knowledge.description.trim() === '') {
				toast.error($i18n.t('Please fill in all fields.'));
				return;
			}

			const res = await updateKnowledgeById(localStorage.token, id, {
				...knowledge,
				name: knowledge.name,
				description: knowledge.description,
				access_control: knowledge.access_control
			}).catch((e) => {
				toast.error(`${e}`);
			});

			if (res) {
				toast.success($i18n.t('Knowledge updated successfully'));
				_knowledge.set(await getKnowledgeBases(localStorage.token));
			}
		}, 1000);
	};

	const handleMediaQuery = async (e) => {
		if (e.matches) {
			largeScreen = true;
		} else {
			largeScreen = false;
		}
	};

	const onDragOver = (e) => {
		e.preventDefault();

		// Check if a file is being draggedOver.
		if (e.dataTransfer?.types?.includes('Files')) {
			dragged = true;
		} else {
			dragged = false;
		}
	};

	const onDragLeave = () => {
		dragged = false;
	};

	const onDrop = async (e) => {
		e.preventDefault();
		dragged = false;

		if (e.dataTransfer?.types?.includes('Files')) {
			if (e.dataTransfer?.files) {
				const inputFiles = e.dataTransfer?.files;

				if (inputFiles && inputFiles.length > 0) {
					for (const file of inputFiles) {
						await uploadFileHandler(file);
					}
				} else {
					toast.error($i18n.t(`File not found.`));
				}
			}
		}
	};

	onMount(async () => {
		// listen to resize 1024px
		mediaQuery = window.matchMedia('(min-width: 1024px)');

		mediaQuery.addEventListener('change', handleMediaQuery);
		handleMediaQuery(mediaQuery);

		// Select the container element you want to observe
		const container = document.getElementById('collection-container');

		// initialize the minSize based on the container width
		minSize = !largeScreen ? 100 : Math.floor((300 / container.clientWidth) * 100);

		// Create a new ResizeObserver instance
		const resizeObserver = new ResizeObserver((entries) => {
			for (let entry of entries) {
				const width = entry.contentRect.width;
				// calculate the percentage of 300
				const percentage = (300 / width) * 100;
				// set the minSize to the percentage, must be an integer
				minSize = !largeScreen ? 100 : Math.floor(percentage);

				if (showSidepanel) {
					if (pane && pane.isExpanded() && pane.getSize() < minSize) {
						pane.resize(minSize);
					}
				}
			}
		});

		// Start observing the container's size changes
		resizeObserver.observe(container);

		if (pane) {
			pane.expand();
		}

		id = $page.params.id;

		const res = await getKnowledgeById(localStorage.token, id).catch((e) => {
			toast.error(`${e}`);
			return null;
		});

		if (res) {
			knowledge = res;
		} else {
			goto('/workspace/knowledge');
		}

		const dropZone = document.querySelector('body');
		dropZone?.addEventListener('dragover', onDragOver);
		dropZone?.addEventListener('drop', onDrop);
		dropZone?.addEventListener('dragleave', onDragLeave);
	});

	onDestroy(() => {
		mediaQuery?.removeEventListener('change', handleMediaQuery);
		const dropZone = document.querySelector('body');
		dropZone?.removeEventListener('dragover', onDragOver);
		dropZone?.removeEventListener('drop', onDrop);
		dropZone?.removeEventListener('dragleave', onDragLeave);
	});

	const processFiles = async (selectedFiles) => {
		let files = [];
		let errors = [];
		let totalFiles = selectedFiles.length;
		let uploadedFiles = 0;

		const toastId = toast.loading(`Uploading files: 0/${totalFiles} (0%)`, { duration: Infinity });

		const updateProgress = () => {
			const percentage = ((uploadedFiles / totalFiles) * 100).toFixed(2);

			toast.info(`Uploading files: ${uploadedFiles}/${totalFiles} (${percentage}%)`, {
				id: toastId,
				duration: Infinity
			});
		};

		const batchSize = 5;
		const fileBatches = chunkArray([...selectedFiles], batchSize);

		for (const batch of fileBatches) {
			await Promise.all(
				batch.map(async (file) => {
					const processedFile = await processSingleFile(file, files, errors);
					if (processedFile) {
						await sendFile(processedFile, errors);
						uploadedFiles++;
						updateProgress();
					}
				})
			);
		}

		toast.success(`Upload complete! ${totalFiles}/${totalFiles} files uploaded`, {
			id: toastId,
			duration: 3000
		});
	};


	const processSingleFile = async (file, files, errors) => {
		try {
			let processedFile = null;

			if (file.type.startsWith('text')) {
				const text = await readFileAsText(file);
				processedFile = { name: file.name, content: text, collection_name: id };
			} else if (file.type === 'application/pdf') {
				const text = await recognizePdfText(file);
				processedFile = { name: file.name, content: text, collection_name: id };
			} else if (file.type.startsWith('image')) {
				const text = await recognizeText(file);
				processedFile = { name: file.name, content: text, collection_name: id };
			} else if (
				file.type === 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
			) {
				const text = await extractExcelText(file);
				processedFile = { name: file.name, content: text, collection_name: id };
			} else if (
				file.type === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
			) {
				const text = await extractWordText(file);
				processedFile = { name: file.name, content: text, collection_name: id };
			} else {
				errors.push(`Unsupported file type: ${file.name}`);
				return null;
			}

			files.push(processedFile);
			filteredDirectoryItems = [...filteredDirectoryItems, processedFile];

			return processedFile;
		} catch (error) {
			errors.push(`Error processing file ${file.name}: ${error.message}`);
			return null;
		}
	};

	const readFileAsText = (file) => {
		return new Promise((resolve, reject) => {
			const reader = new FileReader();
			reader.onload = (e) => resolve(e.target.result);
			reader.onerror = () => reject(new Error(`Error reading file ${file.name}`));
			reader.readAsText(file);
		});
	};

	const recognizeText = (file) => {
		return new Promise((resolve, reject) => {
			Tesseract.recognize(URL.createObjectURL(file), 'eng+heb')
				.then(({ data: { text } }) => {
					resolve(text);
				})
				.catch((error) => {
					reject(error);
				});
		});
	};

	const extractWordText = (file) => {
		console.log(file, 'dsadas');
		return new Promise((resolve, reject) => {
			const reader = new FileReader();
			reader.onload = async (e) => {
				try {
					const arrayBuffer = e.target.result;
					const { value } = await mammoth.extractRawText({ arrayBuffer });
					resolve(value.trim());
				} catch (error) {
					reject(new Error(`Ошибка извлечения текста из Word: ${error.message}`));
				}
			};

			reader.onerror = () => reject(new Error(`Ошибка чтения файла ${file.name}`));
			reader.readAsArrayBuffer(file);
		});
	};

	const extractExcelText = (file) => {
		return new Promise((resolve, reject) => {
			const reader = new FileReader();
			reader.onload = (e) => {
				try {
					const data = new Uint8Array(e.target.result);
					const workbook = XLSX.read(data, { type: 'array' });

					let textContent = '';
					workbook.SheetNames.forEach((sheetName) => {
						const sheet = workbook.Sheets[sheetName];
						const sheetData = XLSX.utils.sheet_to_csv(sheet, {
							blankrows: false,
							skipHidden: true
						});

						textContent += sheetData + '\n';
					});

					resolve(textContent.trim());
				} catch (error) {
					reject(new Error(`Ошибка чтения Excel: ${error.message}`));
				}
			};
			reader.onerror = () => reject(new Error(`Ошибка чтения файла ${file.name}`));
			reader.readAsArrayBuffer(file);
		});
	};

	const recognizePdfText = async (file) => {
		const reader = new FileReader();

		const text = await new Promise((resolve, reject) => {
			reader.onload = async (e) => {
				try {
					const pdfData = new Uint8Array(e.target.result);
					const pdf = await pdfjsLib.getDocument(pdfData).promise;

					let textContent = '';

					for (let pageNum = 1; pageNum <= pdf.numPages; pageNum++) {
						const page = await pdf.getPage(pageNum);
						const content = await page.getTextContent();

						if (content.items.length > 0) {
							content.items.forEach((item) => {
								textContent += item.str + ' ';
							});
						} else {
							const scale = 2;
							const viewport = page.getViewport({ scale });

							const canvas = document.createElement('canvas');
							const context = canvas.getContext('2d');
							context.filter = 'contrast(200%)';
							canvas.width = viewport.width;
							canvas.height = viewport.height;

							await page.render({ canvasContext: context, viewport }).promise;
							const imageData = canvas.toDataURL('image/png');

							const { data } = await Tesseract.recognize(imageData, 'eng+heb', {
								tessedit_pageseg_mode: Tesseract.PSM.AUTO
							});
							textContent += data.text + ' ';
						}
					}

					resolve(textContent);
				} catch (err) {
					console.error('Ошибка обработки PDF:', err);
					reject(err);
				}
			};

			reader.onerror = (error) => {
				console.error('Ошибка чтения файла:', error);
				reject(error);
			};

			reader.readAsArrayBuffer(file);
		});

		return text;
	};

	const sendFiles = async (files, errors) => {
		if (files.length === 0) return;

		const batchSize = 5;
		const fileBatches = chunkArray(files, batchSize);

		for (const batch of fileBatches) {
			await Promise.all(batch.map((file) => sendFile(file, errors)));
		}
	};

	const sendFile = async (file, errors) => {
		try {
			const response = await fetch(`${WEBUI_BASE_URL}/api/v1/retrieval/process/text`, {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
					authorization: 'Bearer ' + localStorage.getItem('token')
				},
				body: JSON.stringify({
					name: file.name,
					content: file.content,
					collection_name: file.collection_name
				})
			});
			setTimeout(async () => {
				await fetchCollectionData();
			}, 2000);
			if (!response.ok) throw new Error(`Failed to upload: ${file.name}`);
		} catch (error) {
			errors.push(error.message);
		}
	};

	const chunkArray = (array, size) => {
		const chunks = [];
		for (let i = 0; i < array.length; i += size) {
			chunks.push(array.slice(i, i + size));
		}
		return chunks;
	};

	const handleFileChange = async (e) => {
		await processFiles(e.target.files);
		e.target.value = '';
	};
</script>

{#if dragged}
	<div
		class="fixed {$showSidebar
			? 'left-0 md:left-[260px] md:w-[calc(100%-260px)]'
			: 'left-0'}  w-full h-full flex z-50 touch-none pointer-events-none"
		id="dropzone"
		role="region"
		aria-label="Drag and Drop Container"
	>
		<div class="absolute w-full h-full backdrop-blur-sm bg-gray-800/40 flex justify-center">
			<div class="m-auto pt-64 flex flex-col justify-center">
				<div class="max-w-md">
					<AddFilesPlaceholder>
						<div class=" mt-2 text-center text-sm dark:text-gray-200 w-full">
							Drop any files here to add to my documents
						</div>
					</AddFilesPlaceholder>
				</div>
			</div>
		</div>
	</div>
{/if}

<SyncConfirmDialog
	bind:show={showSyncConfirmModal}
	message={$i18n.t(
		'This will reset the knowledge base and sync all files. Do you wish to continue?'
	)}
	on:confirm={() => {
		syncDirectoryHandler();
	}}
/>

<AddTextContentModal
	bind:show={showAddTextContentModal}
	on:submit={(e) => {
		const file = createFileFromText(e.detail.name, e.detail.content);
		uploadFileHandler(file);
	}}
/>

<input
	bind:files={inputFiles}
	hidden
	id="files-input"
	multiple
	on:change={async () => {
		if (inputFiles && inputFiles.length > 0) {
			for (const file of inputFiles) {
				await uploadFileHandler(file);
			}

			inputFiles = null;
			const fileInputElement = document.getElementById('files-input');

			if (fileInputElement) {
				fileInputElement.value = '';
			}
		} else {
			toast.error($i18n.t(`File not found.`));
		}
	}}
	type="file"
/>

<input hidden id="directory-input" on:change={handleFileChange} type="file" webkitdirectory />

<div class="flex flex-col w-full translate-y-1" id="collection-container">
	{#if id && knowledge}
		<AccessControlModal
			bind:show={showAccessControlModal}
			bind:accessControl={knowledge.access_control}
			onChange={() => {
				changeDebounceHandler();
			}}
			accessRoles={['read', 'write']}
		/>
		<div class="w-full mb-2.5">
			<div class=" flex w-full">
				<div class="flex-1">
					<div class="flex items-center justify-between w-full px-0.5 mb-1">
						<div class="w-full">
							<input
								type="text"
								class="text-left w-full font-semibold text-2xl font-primary bg-transparent outline-hidden"
								bind:value={knowledge.name}
								placeholder="Knowledge Name"
								on:input={() => {
									changeDebounceHandler();
								}}
							/>
						</div>

						<div class="self-center shrink-0">
							<button
								class="bg-gray-50 hover:bg-gray-100 text-black dark:bg-gray-850 dark:hover:bg-gray-800 dark:text-white transition px-2 py-1 rounded-full flex gap-1 items-center"
								type="button"
								on:click={() => {
									showAccessControlModal = true;
								}}
							>
								<LockClosed strokeWidth="2.5" className="size-3.5" />

								<div class="text-sm font-medium shrink-0">
									{$i18n.t('Access')}
								</div>
							</button>
						</div>
					</div>

					<div class="flex w-full px-1">
						<input
							type="text"
							class="text-left text-xs w-full text-gray-500 bg-transparent outline-hidden"
							bind:value={knowledge.description}
							placeholder="Knowledge Description"
							on:input={() => {
								changeDebounceHandler();
							}}
						/>
					</div>
				</div>
			</div>
		</div>

		<div class="flex flex-row flex-1 h-full max-h-full pb-2.5 gap-3">
			{#if largeScreen}
				<div class="flex-1 flex justify-start w-full h-full max-h-full">
					{#if selectedFile}
						<div class=" flex flex-col w-full h-full max-h-full">
							<div class="shrink-0 mb-2 flex items-center">
								{#if !showSidepanel}
									<div class="-translate-x-2">
										<button
											class="w-full text-left text-sm p-1.5 rounded-lg dark:text-gray-300 dark:hover:text-white hover:bg-black/5 dark:hover:bg-gray-850"
											on:click={() => {
												pane.expand();
											}}
										>
											<ChevronLeft strokeWidth="2.5" />
										</button>
									</div>
								{/if}

								<div class=" flex-1 text-xl font-medium">
									<a
										class="hover:text-gray-500 dark:hover:text-gray-100 hover:underline grow line-clamp-1"
										href={selectedFile.id ? `/api/v1/files/${selectedFile.id}/content` : '#'}
										target="_blank"
									>
										{selectedFile?.meta?.name}
									</a>
								</div>

								<div>
									<button
										class="self-center w-fit text-sm py-1 px-2.5 dark:text-gray-300 dark:hover:text-white hover:bg-black/5 dark:hover:bg-white/5 rounded-lg"
										on:click={() => {
											updateFileContentHandler();
										}}
									>
										{$i18n.t('Save')}
									</button>
								</div>
							</div>

							<div
								class=" flex-1 w-full h-full max-h-full text-sm bg-transparent outline-hidden overflow-y-auto scrollbar-hidden"
							>
								{#key selectedFile.id}
									<RichTextInput
										className="input-prose-sm"
										bind:value={selectedFile.data.content}
										placeholder={$i18n.t('Add content here')}
										preserveBreaks={true}
									/>
								{/key}
							</div>
						</div>
					{:else}
						<div class="h-full flex w-full">
							<div class="m-auto text-xs text-center text-gray-200 dark:text-gray-700">
								{$i18n.t('Drag and drop a file to upload or select a file to view')}
							</div>
						</div>
					{/if}
				</div>
			{:else if !largeScreen && selectedFileId !== null}
				<Drawer
					className="h-full"
					show={selectedFileId !== null}
					on:close={() => {
						selectedFileId = null;
					}}
				>
					<div class="flex flex-col justify-start h-full max-h-full p-2">
						<div class=" flex flex-col w-full h-full max-h-full">
							<div class="shrink-0 mt-1 mb-2 flex items-center">
								<div class="mr-2">
									<button
										class="w-full text-left text-sm p-1.5 rounded-lg dark:text-gray-300 dark:hover:text-white hover:bg-black/5 dark:hover:bg-gray-850"
										on:click={() => {
											selectedFileId = null;
										}}
									>
										<ChevronLeft strokeWidth="2.5" />
									</button>
								</div>
								<div class=" flex-1 text-xl line-clamp-1">
									{selectedFile?.meta?.name}
								</div>

								<div>
									<button
										class="self-center w-fit text-sm py-1 px-2.5 dark:text-gray-300 dark:hover:text-white hover:bg-black/5 dark:hover:bg-white/5 rounded-lg"
										on:click={() => {
											updateFileContentHandler();
										}}
									>
										{$i18n.t('Save')}
									</button>
								</div>
							</div>

							<div
								class=" flex-1 w-full h-full max-h-full py-2.5 px-3.5 rounded-lg text-sm bg-transparent overflow-y-auto scrollbar-hidden"
							>
								{#key selectedFile.id}
									<RichTextInput
										className="input-prose-sm"
										bind:value={selectedFile.data.content}
										placeholder={$i18n.t('Add content here')}
										preserveBreaks={true}
									/>
								{/key}
							</div>
						</div>
					</div>
				</Drawer>
			{/if}

			<div
				class="{largeScreen ? 'shrink-0 w-72 max-w-72' : 'flex-1'}
			flex
			py-2
			rounded-2xl
			border
			border-gray-50
			h-full
			dark:border-gray-850"
			>
				<div class=" flex flex-col w-full space-x-2 rounded-lg h-full">
					<div class="w-full h-full flex flex-col">
						<div class=" px-3">
							<div class="flex mb-0.5">
								<div class=" self-center ml-1 mr-3">
									<svg
										xmlns="http://www.w3.org/2000/svg"
										viewBox="0 0 20 20"
										fill="currentColor"
										class="w-4 h-4"
									>
										<path
											fill-rule="evenodd"
											d="M9 3.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM2 9a7 7 0 1112.452 4.391l3.328 3.329a.75.75 0 11-1.06 1.06l-3.329-3.328A7 7 0 012 9z"
											clip-rule="evenodd"
										/>
									</svg>
								</div>
								<input
									class=" w-full text-sm pr-4 py-1 rounded-r-xl outline-hidden bg-transparent"
									bind:value={query}
									placeholder={$i18n.t('Search Collection')}
									on:focus={() => {
										selectedFileId = null;
									}}
								/>

								<div>
									<AddContentMenu
										on:upload={(e) => {
											if (e.detail.type === 'directory') {
												uploadDirectoryHandler();
											} else if (e.detail.type === 'text') {
												showAddTextContentModal = true;
											} else {
												document.getElementById('files-input').click();
											}
										}}
										on:sync={(e) => {
											showSyncConfirmModal = true;
										}}
										on:scan={(e) => {
											if (e.detail.type === 'documents') {
												document.getElementById('directory-input').click();
											}
										}}
									/>
								</div>
							</div>
						</div>
						{#if filteredDirectoryItems.length > 0}
							<div class=" flex overflow-y-auto h-full w-full scrollbar-hidden text-xs">
								<Files
									files={filteredDirectoryItems}
									on:click={(e) => {
										selectedFileId = selectedFileId === e.detail ? null : e.detail;
									}}
									{selectedFileId}
									on:delete={(e) => {
										selectedFileId = null;
										deleteDirectoryFileHandler(e.detail);
									}}
								/>
							</div>
						{:else if !filteredDirectoryItems.length}
							<div class="my-3 flex flex-col justify-center text-center text-gray-500 text-xs">
								<div>
									{$i18n.t('No content found')}
								</div>
							</div>
						{/if}
					</div>
				</div>
			</div>
		</div>
	{:else}
		<Spinner />
	{/if}
</div>
